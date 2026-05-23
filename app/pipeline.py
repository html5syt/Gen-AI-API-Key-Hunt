from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
import queue
import threading
import time
from typing import Any

from app.config import AppConfig, ChannelConfig, ConfigManager
from app.database import Database
from app.searcher import Candidate, GitHubSearcher
from app.validator import Validator


@dataclass(slots=True)
class ValidationTask:
    channel_name: str
    provider: str
    api_key: str
    repository: str = ""
    file_path: str = ""
    file_url: str = ""
    matched_line: str = ""
    proxy: str = ""
    source: str = "scan"


@dataclass(slots=True)
class RuntimeState:
    started_at: float = 0
    last_cycle_started_at: float = 0
    last_cycle_finished_at: float = 0
    last_validation_sweep_at: float = 0
    total_search_hits: int = 0
    total_new_found: int = 0
    total_validation_runs: int = 0
    total_validation_sweeps: int = 0
    queue_size: int = 0


class ScanPipeline:
    def __init__(self, config_manager: ConfigManager, database: Database) -> None:
        self.config_manager = config_manager
        self.database = database
        self._stop_event = threading.Event()
        self._scan_event = threading.Event()
        self._queue: queue.Queue[ValidationTask] = queue.Queue(maxsize=50000)
        self._scheduler_thread: threading.Thread | None = None
        self._sweeper_thread: threading.Thread | None = None
        self._validator_threads: list[threading.Thread] = []
        self._state_lock = threading.RLock()
        self._state = RuntimeState()

    def start(self) -> None:
        cfg = self.config_manager.get()
        self._state.started_at = time.time()
        self._start_validator_workers(cfg)
        self._scheduler_thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self._scheduler_thread.start()
        self._sweeper_thread = threading.Thread(
            target=self._validation_sweep_loop, daemon=True
        )
        self._sweeper_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._scan_event.set()
        if self._scheduler_thread is not None:
            self._scheduler_thread.join(timeout=5)
        if self._sweeper_thread is not None:
            self._sweeper_thread.join(timeout=5)
        for thread in self._validator_threads:
            thread.join(timeout=2)

    def trigger_scan_now(self) -> None:
        self._scan_event.set()

    def runtime_stats(self) -> dict[str, Any]:
        with self._state_lock:
            return {
                "started_at": self._state.started_at,
                "last_cycle_started_at": self._state.last_cycle_started_at,
                "last_cycle_finished_at": self._state.last_cycle_finished_at,
                "last_validation_sweep_at": self._state.last_validation_sweep_at,
                "total_search_hits": self._state.total_search_hits,
                "total_new_found": self._state.total_new_found,
                "total_validation_runs": self._state.total_validation_runs,
                "total_validation_sweeps": self._state.total_validation_sweeps,
                "queue_size": self._queue.qsize(),
            }

    def _start_validator_workers(self, cfg: AppConfig) -> None:
        for idx in range(max(1, cfg.scanner.validate_workers)):
            thread = threading.Thread(target=self._validator_worker, args=(idx,), daemon=True)
            thread.start()
            self._validator_threads.append(thread)

    def _scheduler_loop(self) -> None:
        while not self._stop_event.is_set():
            cfg = self.config_manager.get()
            self._run_scan_cycle(cfg)
            self._scan_event.wait(timeout=max(5, cfg.scanner.interval_seconds))
            self._scan_event.clear()

    def _validation_sweep_loop(self) -> None:
        while not self._stop_event.is_set():
            cfg = self.config_manager.get()
            self._enqueue_sweep_tasks(cfg)
            with self._state_lock:
                self._state.last_validation_sweep_at = time.time()
                self._state.total_validation_sweeps += 1
                self._state.queue_size = self._queue.qsize()
            self._stop_event.wait(
                timeout=max(60, cfg.validation.revalidation_interval_seconds)
            )

    def _enqueue_sweep_tasks(self, cfg: AppConfig) -> None:
        pending_rows = self.database.list_pending_found(
            limit=max(1, cfg.validation.pending_batch_size)
        )
        for row in pending_rows:
            self._queue.put(
                ValidationTask(
                    channel_name=row["channel_name"],
                    provider=row["provider"],
                    api_key=row["api_key"],
                    repository=row["repository"],
                    file_path=row["file_path"],
                    file_url=row["file_url"],
                    matched_line=row["matched_line"],
                    proxy=self._resolve_proxy(
                        cfg, row["channel_name"], row["provider"]
                    ),
                    source="pending",
                )
            )

        validated_rows = self.database.list_random_validated(
            limit=max(0, cfg.validation.validated_sample_size)
        )
        for row in validated_rows:
            self._queue.put(
                ValidationTask(
                    channel_name=row["provider"],
                    provider=row["provider"],
                    api_key=row["api_key"],
                    proxy=self._resolve_proxy(cfg, row["provider"], row["provider"]),
                    source="sampled",
                )
            )

    def _resolve_proxy(self, cfg: AppConfig, channel_name: str, provider: str) -> str:
        for channel in cfg.channels:
            if channel.name == channel_name or channel.provider == provider:
                return channel.proxy
        return ""

    def _run_scan_cycle(self, cfg: AppConfig) -> None:
        with self._state_lock:
            self._state.last_cycle_started_at = time.time()

        searcher = GitHubSearcher(cfg.github)
        channels = [channel for channel in cfg.channels if channel.enabled]

        if not channels or not cfg.github.tokens:
            with self._state_lock:
                self._state.last_cycle_finished_at = time.time()
            return

        with ThreadPoolExecutor(max_workers=max(1, cfg.scanner.search_workers)) as executor:
            futures: list[Future[int]] = []
            for channel in channels:
                futures.append(executor.submit(self._scan_single_channel, searcher, channel))
            for future in futures:
                hits = future.result()
                with self._state_lock:
                    self._state.total_search_hits += hits
                    self._state.queue_size = self._queue.qsize()

        with self._state_lock:
            self._state.last_cycle_finished_at = time.time()
            self._state.queue_size = self._queue.qsize()

    def _scan_single_channel(self, searcher: GitHubSearcher, channel: ChannelConfig) -> int:
        proxy = channel.proxy

        def emit(candidate: Candidate) -> None:
            inserted = self.database.insert_found_key(
                channel_name=candidate.channel_name,
                provider=candidate.provider,
                api_key=candidate.api_key,
                repository=candidate.repository,
                file_path=candidate.file_path,
                file_url=candidate.file_url,
                matched_line=candidate.matched_line,
            )
            if inserted:
                self._queue.put(
                    ValidationTask(
                        channel_name=candidate.channel_name,
                        provider=candidate.provider,
                        api_key=candidate.api_key,
                        repository=candidate.repository,
                        file_path=candidate.file_path,
                        file_url=candidate.file_url,
                        matched_line=candidate.matched_line,
                        proxy=proxy,
                        source="scan",
                    )
                )
                with self._state_lock:
                    self._state.total_new_found += 1
                    self._state.queue_size = self._queue.qsize()

        return searcher.run_channel(channel, emit=emit, should_stop=self._stop_event.is_set)

    def _validator_worker(self, _worker_idx: int) -> None:
        while not self._stop_event.is_set():
            try:
                task = self._queue.get(timeout=1)
            except queue.Empty:
                continue

            try:
                cfg = self.config_manager.get()
                validator = Validator(cfg)
                result = validator.validate(
                    task.channel_name, task.provider, task.api_key, proxy=task.proxy
                )
                self.database.update_validation(
                    task.provider,
                    task.api_key,
                    result.status,
                    result.detail,
                    channel_name=task.channel_name,
                    repository=task.repository,
                    file_path=task.file_path,
                    file_url=task.file_url,
                    matched_line=task.matched_line,
                    source=task.source,
                )
                if result.status == "INVALID" and cfg.validation.delete_invalid_keys:
                    self.database.delete_key(task.provider, task.api_key)

                with self._state_lock:
                    self._state.total_validation_runs += 1
                    self._state.queue_size = self._queue.qsize()
            finally:
                self._queue.task_done()
