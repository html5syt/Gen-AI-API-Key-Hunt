from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import sqlite3
import threading
from typing import Any


@dataclass(slots=True)
class FoundKeyRecord:
    id: int
    channel_name: str
    provider: str
    api_key: str
    repository: str
    file_path: str
    file_url: str
    matched_line: str
    first_seen_at: str
    last_seen_at: str
    validation_status: str
    last_validated_at: str


class Database:
    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._init()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path, check_same_thread=False)
        con.row_factory = sqlite3.Row
        return con

    def _init(self) -> None:
        with self._connect() as con:
            cur = con.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS found_keys (
                    id INTEGER PRIMARY KEY,
                    channel_name TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    api_key TEXT NOT NULL,
                    repository TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    file_url TEXT NOT NULL,
                    matched_line TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    validation_status TEXT NOT NULL DEFAULT 'PENDING',
                    last_validated_at TEXT NOT NULL DEFAULT ''
                )
                """
            )
            cur.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_found_unique
                ON found_keys(provider, api_key, repository, file_path)
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS validated_keys (
                    id INTEGER PRIMARY KEY,
                    provider TEXT NOT NULL,
                    api_key TEXT NOT NULL,
                    status TEXT NOT NULL,
                    last_validated_at TEXT NOT NULL,
                    UNIQUE(provider, api_key)
                )
                """
            )
            con.commit()

    def insert_found_key(
        self,
        channel_name: str,
        provider: str,
        api_key: str,
        repository: str,
        file_path: str,
        file_url: str,
        matched_line: str,
    ) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connect() as con:
            cur = con.cursor()
            cur.execute(
                """
                INSERT OR IGNORE INTO found_keys (
                    channel_name, provider, api_key, repository, file_path, file_url, matched_line,
                    first_seen_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (channel_name, provider, api_key, repository, file_path, file_url, matched_line, now, now),
            )
            inserted = cur.rowcount > 0
            if not inserted:
                cur.execute(
                    """
                    UPDATE found_keys
                    SET last_seen_at = ?
                    WHERE provider = ? AND api_key = ? AND repository = ? AND file_path = ?
                    """,
                    (now, provider, api_key, repository, file_path),
                )
            con.commit()
            return inserted

    def update_validation(self, provider: str, api_key: str, status: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connect() as con:
            cur = con.cursor()
            cur.execute(
                """
                UPDATE found_keys
                SET validation_status = ?, last_validated_at = ?
                WHERE provider = ? AND api_key = ?
                """,
                (status, now, provider, api_key),
            )
            if status in {"VALID", "QUOTA_EXCEEDED"}:
                cur.execute(
                    """
                    INSERT INTO validated_keys(provider, api_key, status, last_validated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(provider, api_key)
                    DO UPDATE SET status = excluded.status, last_validated_at = excluded.last_validated_at
                    """,
                    (provider, api_key, status, now),
                )
            con.commit()

    def list_found(self, limit: int, offset: int, status: str | None = None) -> list[FoundKeyRecord]:
        with self._connect() as con:
            cur = con.cursor()
            if status:
                cur.execute(
                    """
                    SELECT * FROM found_keys
                    WHERE validation_status = ?
                    ORDER BY id DESC
                    LIMIT ? OFFSET ?
                    """,
                    [status, limit, offset],
                )
            else:
                cur.execute(
                    """
                    SELECT * FROM found_keys
                    ORDER BY id DESC
                    LIMIT ? OFFSET ?
                    """,
                    [limit, offset],
                )
            rows = cur.fetchall()
        result: list[FoundKeyRecord] = []
        for row in rows:
            result.append(
                FoundKeyRecord(
                    id=int(row["id"]),
                    channel_name=str(row["channel_name"]),
                    provider=str(row["provider"]),
                    api_key=str(row["api_key"]),
                    repository=str(row["repository"]),
                    file_path=str(row["file_path"]),
                    file_url=str(row["file_url"]),
                    matched_line=str(row["matched_line"]),
                    first_seen_at=str(row["first_seen_at"]),
                    last_seen_at=str(row["last_seen_at"]),
                    validation_status=str(row["validation_status"]),
                    last_validated_at=str(row["last_validated_at"]),
                )
            )
        return result

    def list_validated(self, limit: int, offset: int, provider: str | None = None) -> list[dict[str, str]]:
        with self._connect() as con:
            cur = con.cursor()
            if provider:
                cur.execute(
                    """
                    SELECT provider, api_key, status, last_validated_at
                    FROM validated_keys
                    WHERE provider = ?
                    ORDER BY id DESC
                    LIMIT ? OFFSET ?
                    """,
                    [provider, limit, offset],
                )
            else:
                cur.execute(
                    """
                    SELECT provider, api_key, status, last_validated_at
                    FROM validated_keys
                    ORDER BY id DESC
                    LIMIT ? OFFSET ?
                    """,
                    [limit, offset],
                )
            rows = cur.fetchall()
        return [
            {
                "provider": str(row["provider"]),
                "api_key": str(row["api_key"]),
                "status": str(row["status"]),
                "last_validated_at": str(row["last_validated_at"]),
            }
            for row in rows
        ]

    def get_stats(self) -> dict[str, Any]:
        with self._connect() as con:
            cur = con.cursor()
            cur.execute("SELECT COUNT(*) AS c FROM found_keys")
            total_found = int(cur.fetchone()["c"])
            cur.execute("SELECT COUNT(*) AS c FROM validated_keys")
            total_validated = int(cur.fetchone()["c"])
            cur.execute("SELECT provider, COUNT(*) AS c FROM found_keys GROUP BY provider ORDER BY c DESC")
            found_by_provider = [{"provider": str(row["provider"]), "count": int(row["c"])} for row in cur.fetchall()]
            cur.execute("SELECT validation_status, COUNT(*) AS c FROM found_keys GROUP BY validation_status ORDER BY c DESC")
            status_breakdown = [{"status": str(row["validation_status"]), "count": int(row["c"])} for row in cur.fetchall()]
        return {
            "total_found": total_found,
            "total_validated": total_validated,
            "found_by_provider": found_by_provider,
            "status_breakdown": status_breakdown,
        }

    def export_validated_csv(self, output_path: str) -> int:
        rows = self.list_validated(limit=1000000, offset=0)
        with open(output_path, "w", newline="", encoding="utf-8") as file_obj:
            writer = csv.DictWriter(file_obj, fieldnames=["provider", "api_key", "status", "last_validated_at"])
            writer.writeheader()
            writer.writerows(rows)
        return len(rows)
