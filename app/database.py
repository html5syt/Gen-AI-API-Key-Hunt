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
    validation_detail: str


@dataclass(slots=True)
class ValidationLogRecord:
    id: int
    validated_at: str
    source: str
    channel_name: str
    provider: str
    api_key: str
    repository: str
    file_path: str
    file_url: str
    matched_line: str
    status: str
    detail: str


class Database:
    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._init()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path, check_same_thread=False)
        con.row_factory = sqlite3.Row
        return con

    def _ensure_column(
        self, cur: sqlite3.Cursor, table: str, column: str, ddl: str
    ) -> None:
        cur.execute(f"PRAGMA table_info({table})")
        columns = {row["name"] for row in cur.fetchall()}
        if column not in columns:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    def _order_clause(
        self,
        sort_by: str,
        sort_order: str,
        allowed_columns: dict[str, str],
        default_column: str,
        default_order: str = "DESC",
    ) -> str:
        column = allowed_columns.get(sort_by, default_column)
        order = "ASC" if sort_order.upper() == "ASC" else "DESC"
        return f"{column} {order}, id {order}"

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
                    last_validated_at TEXT NOT NULL DEFAULT '',
                    validation_detail TEXT NOT NULL DEFAULT ''
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
                    detail TEXT NOT NULL DEFAULT '',
                    UNIQUE(provider, api_key)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS validation_logs (
                    id INTEGER PRIMARY KEY,
                    validated_at TEXT NOT NULL,
                    source TEXT NOT NULL,
                    channel_name TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    api_key TEXT NOT NULL,
                    repository TEXT NOT NULL DEFAULT '',
                    file_path TEXT NOT NULL DEFAULT '',
                    file_url TEXT NOT NULL DEFAULT '',
                    matched_line TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT ''
                )
                """
            )
            self._ensure_column(
                cur, "found_keys", "validation_detail", "TEXT NOT NULL DEFAULT ''"
            )
            self._ensure_column(
                cur, "validated_keys", "detail", "TEXT NOT NULL DEFAULT ''"
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

    def update_validation(
        self,
        provider: str,
        api_key: str,
        status: str,
        detail: str,
        *,
        channel_name: str = "",
        repository: str = "",
        file_path: str = "",
        file_url: str = "",
        matched_line: str = "",
        source: str = "validation",
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connect() as con:
            cur = con.cursor()
            if status != "PENDING":
                cur.execute(
                    """
                    INSERT INTO validation_logs(
                        validated_at, source, channel_name, provider, api_key,
                        repository, file_path, file_url, matched_line, status, detail
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        now,
                        source,
                        channel_name,
                        provider,
                        api_key,
                        repository,
                        file_path,
                        file_url,
                        matched_line,
                        status,
                        detail,
                    ),
                )
            cur.execute(
                """
                UPDATE found_keys
                SET validation_status = ?, last_validated_at = ?, validation_detail = ?
                WHERE provider = ? AND api_key = ?
                """,
                (status, now, detail, provider, api_key),
            )
            if status == "VALID":
                cur.execute(
                    """
                    INSERT INTO validated_keys(provider, api_key, status, last_validated_at, detail)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(provider, api_key)
                    DO UPDATE SET status = excluded.status, last_validated_at = excluded.last_validated_at, detail = excluded.detail
                    """,
                    (provider, api_key, status, now, detail),
                )
            con.commit()

    def delete_key(self, provider: str, api_key: str) -> None:
        with self._lock, self._connect() as con:
            cur = con.cursor()
            cur.execute(
                "DELETE FROM found_keys WHERE provider = ? AND api_key = ?",
                [provider, api_key],
            )
            cur.execute(
                "DELETE FROM validated_keys WHERE provider = ? AND api_key = ?",
                [provider, api_key],
            )
            con.commit()

    def list_pending_found(self, limit: int) -> list[dict[str, str]]:
        with self._connect() as con:
            cur = con.cursor()
            cur.execute(
                """
                SELECT channel_name, provider, api_key, repository, file_path, file_url, matched_line
                FROM found_keys
                WHERE validation_status = 'PENDING'
                ORDER BY last_seen_at DESC
                LIMIT ?
                """,
                [limit],
            )
            rows = cur.fetchall()
        return [
            {
                "channel_name": str(row["channel_name"]),
                "provider": str(row["provider"]),
                "api_key": str(row["api_key"]),
                "repository": str(row["repository"]),
                "file_path": str(row["file_path"]),
                "file_url": str(row["file_url"]),
                "matched_line": str(row["matched_line"]),
            }
            for row in rows
        ]

    def list_random_validated(self, limit: int) -> list[dict[str, str]]:
        with self._connect() as con:
            cur = con.cursor()
            cur.execute(
                """
                SELECT provider, api_key
                FROM validated_keys
                ORDER BY RANDOM()
                LIMIT ?
                """,
                [limit],
            )
            rows = cur.fetchall()
        return [
            {
                "provider": str(row["provider"]),
                "api_key": str(row["api_key"]),
            }
            for row in rows
        ]

    def list_found(
        self,
        limit: int,
        offset: int,
        status: str | None = None,
        sort_by: str = "id",
        sort_order: str = "DESC",
    ) -> list[FoundKeyRecord]:
        order_clause = self._order_clause(
            sort_by,
            sort_order,
            {
                "id": "id",
                "channel_name": "channel_name",
                "provider": "provider",
                "api_key": "api_key",
                "repository": "repository",
                "file_path": "file_path",
                "validation_status": "validation_status",
                "first_seen_at": "first_seen_at",
                "last_seen_at": "last_seen_at",
                "last_validated_at": "last_validated_at",
            },
            "id",
        )
        with self._connect() as con:
            cur = con.cursor()
            if status:
                cur.execute(
                    """
                    SELECT * FROM found_keys
                    WHERE validation_status = ?
                    ORDER BY {order_clause}
                    LIMIT ? OFFSET ?
                    """.format(order_clause=order_clause),
                    [status, limit, offset],
                )
            else:
                cur.execute(
                    """
                    SELECT * FROM found_keys
                    ORDER BY {order_clause}
                    LIMIT ? OFFSET ?
                    """.format(order_clause=order_clause),
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
                    validation_detail=str(row["validation_detail"]),
                )
            )
        return result

    def list_validated(
        self,
        limit: int,
        offset: int,
        provider: str | None = None,
        sort_by: str = "id",
        sort_order: str = "DESC",
    ) -> list[dict[str, str]]:
        order_clause = self._order_clause(
            sort_by,
            sort_order,
            {
                "id": "id",
                "provider": "provider",
                "api_key": "api_key",
                "status": "status",
                "last_validated_at": "last_validated_at",
                "detail": "detail",
            },
            "id",
        )
        with self._connect() as con:
            cur = con.cursor()
            if provider:
                cur.execute(
                    """
                    SELECT provider, api_key, status, last_validated_at, detail
                    FROM validated_keys
                    WHERE provider = ?
                    ORDER BY {order_clause}
                    LIMIT ? OFFSET ?
                    """.format(order_clause=order_clause),
                    [provider, limit, offset],
                )
            else:
                cur.execute(
                    """
                    SELECT provider, api_key, status, last_validated_at, detail
                    FROM validated_keys
                    ORDER BY {order_clause}
                    LIMIT ? OFFSET ?
                    """.format(order_clause=order_clause),
                    [limit, offset],
                )
            rows = cur.fetchall()
        return [
            {
                "provider": str(row["provider"]),
                "api_key": str(row["api_key"]),
                "status": str(row["status"]),
                "last_validated_at": str(row["last_validated_at"]),
                "detail": str(row["detail"]),
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
            cur.execute("SELECT COUNT(*) AS c FROM validation_logs")
            total_validation_logs = int(cur.fetchone()["c"])
            cur.execute("SELECT provider, COUNT(*) AS c FROM found_keys GROUP BY provider ORDER BY c DESC")
            found_by_provider = [{"provider": str(row["provider"]), "count": int(row["c"])} for row in cur.fetchall()]
            cur.execute("SELECT validation_status, COUNT(*) AS c FROM found_keys GROUP BY validation_status ORDER BY c DESC")
            status_breakdown = [{"status": str(row["validation_status"]), "count": int(row["c"])} for row in cur.fetchall()]
        return {
            "total_found": total_found,
            "total_validated": total_validated,
            "total_validation_logs": total_validation_logs,
            "found_by_provider": found_by_provider,
            "status_breakdown": status_breakdown,
        }

    def list_validation_logs(
        self,
        limit: int,
        offset: int,
        status: str | None = None,
        sort_by: str = "id",
        sort_order: str = "DESC",
    ) -> list[ValidationLogRecord]:
        order_clause = self._order_clause(
            sort_by,
            sort_order,
            {
                "id": "id",
                "validated_at": "validated_at",
                "source": "source",
                "channel_name": "channel_name",
                "provider": "provider",
                "api_key": "api_key",
                "status": "status",
                "detail": "detail",
            },
            "id",
        )
        with self._connect() as con:
            cur = con.cursor()
            if status:
                cur.execute(
                    """
                    SELECT * FROM validation_logs
                    WHERE status = ?
                    ORDER BY {order_clause}
                    LIMIT ? OFFSET ?
                    """.format(order_clause=order_clause),
                    [status, limit, offset],
                )
            else:
                cur.execute(
                    """
                    SELECT * FROM validation_logs
                    ORDER BY {order_clause}
                    LIMIT ? OFFSET ?
                    """.format(order_clause=order_clause),
                    [limit, offset],
                )
            rows = cur.fetchall()
        return [
            ValidationLogRecord(
                id=int(row["id"]),
                validated_at=str(row["validated_at"]),
                source=str(row["source"]),
                channel_name=str(row["channel_name"]),
                provider=str(row["provider"]),
                api_key=str(row["api_key"]),
                repository=str(row["repository"]),
                file_path=str(row["file_path"]),
                file_url=str(row["file_url"]),
                matched_line=str(row["matched_line"]),
                status=str(row["status"]),
                detail=str(row["detail"]),
            )
            for row in rows
        ]

    def export_validated_csv(self, output_path: str) -> int:
        written = 0
        with self._connect() as con, open(output_path, "w", newline="", encoding="utf-8") as file_obj:
            cur = con.cursor()
            cur.execute(
                """
                SELECT provider, api_key, status, last_validated_at
                FROM validated_keys
                ORDER BY id DESC
                """
            )
            writer = csv.DictWriter(file_obj, fieldnames=["provider", "api_key", "status", "last_validated_at"])
            writer.writeheader()
            while True:
                rows = cur.fetchmany(1000)
                if not rows:
                    break
                for row in rows:
                    writer.writerow(
                        {
                            "provider": str(row["provider"]),
                            "api_key": str(row["api_key"]),
                            "status": str(row["status"]),
                            "last_validated_at": str(row["last_validated_at"]),
                        }
                    )
                    written += 1
        return written
