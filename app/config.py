from __future__ import annotations

from dataclasses import asdict, dataclass, field
import base64
import hashlib
import hmac
from pathlib import Path
import secrets
import threading
from typing import Any

import yaml


@dataclass(slots=True)
class GithubConfig:
    tokens: list[str] = field(default_factory=list)
    user_agent: str = "github-llm-key-searcher/1.0"
    request_timeout_seconds: int = 12
    max_pages: int = 20
    page_delay_seconds: float = 1.0


@dataclass(slots=True)
class ScannerConfig:
    interval_seconds: int = 1800
    search_workers: int = 4
    validate_workers: int = 8


@dataclass(slots=True)
class ValidationConfig:
    request_timeout_seconds: int = 12
    retries: int = 2
    initial_backoff_seconds: int = 1


@dataclass(slots=True)
class WebConfig:
    host: str = "127.0.0.1"
    port: int = 8080
    username: str = "admin"
    password_hash: str = ""
    session_secret: str = "please-change-session-secret"
    page_size: int = 50


@dataclass(slots=True)
class ApiConfig:
    enabled: bool = True
    token: str = "please-change-api-token"


@dataclass(slots=True)
class ChannelConfig:
    name: str
    provider: str
    query: str
    extract_patterns: list[str]
    proxy: str = ""
    enabled: bool = True


@dataclass(slots=True)
class AppConfig:
    github: GithubConfig = field(default_factory=GithubConfig)
    scanner: ScannerConfig = field(default_factory=ScannerConfig)
    validation: ValidationConfig = field(default_factory=ValidationConfig)
    web: WebConfig = field(default_factory=WebConfig)
    api: ApiConfig = field(default_factory=ApiConfig)
    channels: list[ChannelConfig] = field(default_factory=list)


def hash_password(value: str, iterations: int = 260000) -> str:
    salt = base64.urlsafe_b64encode(secrets.token_bytes(16)).decode("ascii").rstrip("=")
    digest = hashlib.pbkdf2_hmac("sha256", value.encode("utf-8"), salt.encode("utf-8"), iterations)
    digest_b64 = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return f"pbkdf2_sha256${iterations}${salt}${digest_b64}"


def verify_password(value: str, stored_hash: str) -> bool:
    if stored_hash.startswith("pbkdf2_sha256$"):
        parts = stored_hash.split("$", 3)
        if len(parts) != 4:
            return False
        _, iter_raw, salt, expected = parts
        try:
            iterations = int(iter_raw)
        except ValueError:
            return False
        digest = hashlib.pbkdf2_hmac("sha256", value.encode("utf-8"), salt.encode("utf-8"), iterations)
        current = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
        return hmac.compare_digest(current, expected)
    return False


def default_channels() -> list[ChannelConfig]:
    return [
        ChannelConfig(
            name="openai",
            provider="openai",
            query="OPENAI_API_KEY=sk-",
            extract_patterns=[r"(sk-proj-[A-Za-z0-9_-]{48,156})", r"(sk-[A-Za-z0-9]{48})"],
        ),
        ChannelConfig(
            name="anthropic",
            provider="anthropic",
            query="ANTHROPIC_API_KEY=sk-ant- OR CLAUDE_API_KEY=sk-ant-",
            extract_patterns=[r"(sk-ant-api03-[A-Za-z0-9_-]{95})", r"(sk-ant-[A-Za-z0-9_-]{44})"],
        ),
        ChannelConfig(
            name="google",
            provider="google",
            query="GOOGLE_API_KEY=AIza OR GEMINI_API_KEY=AIza",
            extract_patterns=[r"(AIza[0-9A-Za-z_-]{35})"],
        ),
        ChannelConfig(
            name="openrouter",
            provider="openrouter",
            query="OPENROUTER_API_KEY=sk-or-v1-",
            extract_patterns=[r"(sk-or-v1-[a-f0-9]{64})"],
        ),
        ChannelConfig(
            name="deepseek",
            provider="deepseek",
            query="DEEPSEEK_API_KEY=sk-",
            extract_patterns=[r"(sk-[a-f0-9]{32})"],
        ),
        ChannelConfig(
            name="groq",
            provider="groq",
            query="GROQ_API_KEY=gsk_",
            extract_patterns=[r"(gsk_[A-Za-z0-9]{48})"],
        ),
        ChannelConfig(
            name="xai",
            provider="xai",
            query="XAI_API_KEY=xai-",
            extract_patterns=[r"(xai-[A-Za-z0-9]{64})"],
        ),
    ]


def default_config() -> AppConfig:
    config = AppConfig(channels=default_channels())
    config.web.password_hash = hash_password("admin")
    return config


class ConfigManager:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        self._config = self._load_or_create()

    def _load_or_create(self) -> AppConfig:
        if not self.path.exists():
            cfg = default_config()
            self.save(cfg)
            return cfg
        return self._from_dict(self._read_yaml())

    def _read_yaml(self) -> dict[str, Any]:
        raw = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return raw
        return {}

    def _from_dict(self, data: dict[str, Any]) -> AppConfig:
        cfg = default_config()
        github_data = data.get("github", {})
        if isinstance(github_data, dict):
            cfg.github.tokens = [str(x) for x in github_data.get("tokens", cfg.github.tokens) if str(x).strip()]
            cfg.github.user_agent = str(github_data.get("user_agent", cfg.github.user_agent))
            cfg.github.request_timeout_seconds = int(github_data.get("request_timeout_seconds", cfg.github.request_timeout_seconds))
            cfg.github.max_pages = int(github_data.get("max_pages", cfg.github.max_pages))
            cfg.github.page_delay_seconds = float(github_data.get("page_delay_seconds", cfg.github.page_delay_seconds))

        scanner_data = data.get("scanner", {})
        if isinstance(scanner_data, dict):
            cfg.scanner.interval_seconds = int(scanner_data.get("interval_seconds", cfg.scanner.interval_seconds))
            cfg.scanner.search_workers = int(scanner_data.get("search_workers", cfg.scanner.search_workers))
            cfg.scanner.validate_workers = int(scanner_data.get("validate_workers", cfg.scanner.validate_workers))

        validation_data = data.get("validation", {})
        if isinstance(validation_data, dict):
            cfg.validation.request_timeout_seconds = int(validation_data.get("request_timeout_seconds", cfg.validation.request_timeout_seconds))
            cfg.validation.retries = int(validation_data.get("retries", cfg.validation.retries))
            cfg.validation.initial_backoff_seconds = int(validation_data.get("initial_backoff_seconds", cfg.validation.initial_backoff_seconds))

        web_data = data.get("web", {})
        if isinstance(web_data, dict):
            cfg.web.host = str(web_data.get("host", cfg.web.host))
            cfg.web.port = int(web_data.get("port", cfg.web.port))
            cfg.web.username = str(web_data.get("username", cfg.web.username))
            cfg.web.password_hash = str(web_data.get("password_hash", cfg.web.password_hash))
            cfg.web.session_secret = str(web_data.get("session_secret", cfg.web.session_secret))
            cfg.web.page_size = int(web_data.get("page_size", cfg.web.page_size))

        api_data = data.get("api", {})
        if isinstance(api_data, dict):
            cfg.api.enabled = bool(api_data.get("enabled", cfg.api.enabled))
            cfg.api.token = str(api_data.get("token", cfg.api.token))

        channels_data = data.get("channels", [])
        channels: list[ChannelConfig] = []
        if isinstance(channels_data, list):
            for item in channels_data:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name", "")).strip()
                provider = str(item.get("provider", "")).strip().lower()
                query = str(item.get("query", "")).strip()
                extract_patterns_raw = item.get("extract_patterns", [])
                if not (name and provider and query and isinstance(extract_patterns_raw, list)):
                    continue
                extract_patterns = [str(p) for p in extract_patterns_raw if str(p).strip()]
                if not extract_patterns:
                    continue
                channels.append(
                    ChannelConfig(
                        name=name,
                        provider=provider,
                        query=query,
                        extract_patterns=extract_patterns,
                        proxy=str(item.get("proxy", "")),
                        enabled=bool(item.get("enabled", True)),
                    )
                )
        if channels:
            cfg.channels = channels
        return cfg

    def get(self) -> AppConfig:
        with self._lock:
            return self._from_dict(asdict(self._config))

    def save(self, config: AppConfig) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            content = yaml.safe_dump(asdict(config), sort_keys=False, allow_unicode=True)
            self.path.write_text(content, encoding="utf-8")
            self._config = config

    def update(self, config: AppConfig) -> None:
        self.save(config)
