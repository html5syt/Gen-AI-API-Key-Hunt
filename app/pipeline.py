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
class RuntimeState:
    started_at: float = 0
    last_cycle_started_at: float = 0
    last_cycle_finished_at: float = 0
    total_search_hits: int = 0
    total_new_found: int = 0
    total_validation_runs: int = 0
    queue_size: int = 0


class ScanPipeline:
    def __init__(self, config_manager: ConfigManager, database: Database) -> None:
        self.config_manager = config_manager
        self.database = database
        self._stop_event = threading.Event()
        self._scan_event = threading.Event()
        self._queue: queue.Queue[tuple[Candidate, str]] = queue.Queue(maxsize=50000)
        self._scheduler_thread: threading.Thread | None = None
        self._validator_threads: list[threading.Thread] = []
        self._state_lock = threading.RLock()
        self._state = RuntimeState()

    def start(self) -> None:
        cfg = self.config_manager.get()
        self._state.started_at = time.time()
        self._start_validator_workers(cfg)
        self._scheduler_thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self._scheduler_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._scan_event.set()
        if self._scheduler_thread is not None:
            self._scheduler_thread.join(timeout=5)
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
                "total_search_hits": self._state.total_search_hits,
                "total_new_found": self._state.total_new_found,
                "total_validation_runs": self._state.total_validation_runs,
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
                self._queue.put((candidate, proxy))
                with self._state_lock:
                    self._state.total_new_found += 1
                    self._state.queue_size = self._queue.qsize()

        return searcher.run_channel(channel, emit=emit, should_stop=self._stop_event.is_set)

    def _validator_worker(self, _worker_idx: int) -> None:
        while not self._stop_event.is_set():
            try:
                candidate, proxy = self._queue.get(timeout=1)
            except queue.Empty:
                continue

            cfg = self.config_manager.get()
            validator = Validator(cfg.validation)
            result = validator.validate(candidate.provider, candidate.api_key, proxy=proxy)
            self.database.update_validation(candidate.provider, candidate.api_key, result.status)

            with self._state_lock:
                self._state.total_validation_runs += 1
                self._state.queue_size = self._queue.qsize()
            self._queue.task_done()
