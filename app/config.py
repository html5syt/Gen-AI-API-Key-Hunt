from __future__ import annotations

from dataclasses import asdict, dataclass, field
import base64
import hashlib
import hmac
import string
from pathlib import Path
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
    interval_seconds: int = 28800
    search_workers: int = 4
    validate_workers: int = 8


@dataclass(slots=True)
class ValidationConfig:
    request_timeout_seconds: int = 12
    retries: int = 2
    initial_backoff_seconds: int = 1
    revalidation_interval_seconds: int = 1800
    pending_batch_size: int = 200
    validated_sample_size: int = 10
    ping_prompt: str = (
        "Reply with a short acknowledgement to confirm the model is reachable."
    )
    delete_invalid_keys: bool = True


@dataclass(slots=True)
class ValidationApiProfile:
    name: str
    api_format: str
    base_url: str
    path: str
    method: str = "POST"
    headers: dict[str, str] = field(default_factory=dict)
    model_candidates: list[str] = field(default_factory=list)
    api_key_transport: str = "header"
    api_key_header: str = "Authorization"
    api_key_prefix: str = "Bearer "
    api_key_query_param: str = "key"
    enabled: bool = True


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
    validation_profile: str = "openai_compat"
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
    validation_profiles: list[ValidationApiProfile] = field(default_factory=list)


def hash_password(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _is_sha256_hex(value: str) -> bool:
    return len(value) == 64 and all(char in string.hexdigits for char in value)


def normalize_secret_hash(value: str) -> str:
    candidate = value.strip()
    if candidate.startswith("sha256$"):
        candidate = candidate.split("$", 1)[1].strip()
    if _is_sha256_hex(candidate):
        return candidate.lower()
    return hash_password(candidate)


def _urlsafe_b64decode_nopad(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def verify_password(value: str, stored_hash: str) -> bool:
    stored = stored_hash.strip()
    if stored.startswith("sha256$"):
        stored = stored.split("$", 1)[1].strip()

    if _is_sha256_hex(stored):
        return hmac.compare_digest(hash_password(value), stored.lower())

    if not stored.startswith("pbkdf2_sha256$"):
        return False

    parts = stored.split("$", 3)
    if len(parts) != 4:
        return False

    _, iter_raw, salt_raw, expected = parts
    try:
        iterations = int(iter_raw)
        if iterations < 1:
            return False
    except ValueError:
        return False

    try:
        salt_bytes = _urlsafe_b64decode_nopad(salt_raw)
        if base64.urlsafe_b64encode(salt_bytes).decode("ascii").rstrip("=") != salt_raw:
            salt_bytes = salt_raw.encode("utf-8")
    except (ValueError, TypeError):
        salt_bytes = salt_raw.encode("utf-8")

    if len(expected) != 43:
        return False

    digest = hashlib.pbkdf2_hmac(
        "sha256", value.encode("utf-8"), salt_bytes, iterations
    )
    current = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return hmac.compare_digest(current, expected)


def verify_secret(value: str, stored_value: str) -> bool:
    return verify_password(value, stored_value)


def default_channels() -> list[ChannelConfig]:
    return [
        ChannelConfig(
            name="openai",
            provider="openai",
            query="OPENAI_API_KEY=sk-",
            extract_patterns=[
                r"(sk-proj-[A-Za-z0-9_-]{48,156})",
                r"(sk-[A-Za-z0-9]{48})",
            ],
            validation_profile="openai_compat",
        ),
        ChannelConfig(
            name="anthropic",
            provider="anthropic",
            query="ANTHROPIC_API_KEY=sk-ant- OR CLAUDE_API_KEY=sk-ant-",
            extract_patterns=[
                r"(sk-ant-api03-[A-Za-z0-9_-]{95})",
                r"(sk-ant-[A-Za-z0-9_-]{44})",
            ],
            validation_profile="anthropic_compat",
        ),
        ChannelConfig(
            name="google",
            provider="google",
            query="GOOGLE_API_KEY=AIza OR GEMINI_API_KEY=AIza",
            extract_patterns=[r"(AIza[0-9A-Za-z_-]{35})"],
            validation_profile="google_compat",
        ),
        ChannelConfig(
            name="openrouter",
            provider="openrouter",
            query="OPENROUTER_API_KEY=sk-or-v1-",
            extract_patterns=[r"(sk-or-v1-[a-f0-9]{64})"],
            validation_profile="openai_compat",
        ),
        ChannelConfig(
            name="deepseek",
            provider="deepseek",
            query="DEEPSEEK_API_KEY=sk-",
            extract_patterns=[r"(sk-[a-f0-9]{32})"],
            validation_profile="openai_compat",
        ),
        ChannelConfig(
            name="groq",
            provider="groq",
            query="GROQ_API_KEY=gsk_",
            extract_patterns=[r"(gsk_[A-Za-z0-9]{48})"],
            validation_profile="openai_compat",
        ),
        ChannelConfig(
            name="xai",
            provider="xai",
            query="XAI_API_KEY=xai-",
            extract_patterns=[r"(xai-[A-Za-z0-9]{64})"],
            validation_profile="openai_compat",
        ),
    ]


def default_validation_profiles() -> list[ValidationApiProfile]:
    return [
        ValidationApiProfile(
            name="openai_compat",
            api_format="openai",
            base_url="https://api.openai.com",
            path="/v1/chat/completions",
            headers={"Content-Type": "application/json"},
            model_candidates=["gpt-4o-mini", "gpt-4.1-mini"],
            api_key_transport="header",
            api_key_header="Authorization",
            api_key_prefix="Bearer ",
        ),
        ValidationApiProfile(
            name="anthropic_compat",
            api_format="anthropic",
            base_url="https://api.anthropic.com",
            path="/v1/messages",
            headers={
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01",
            },
            model_candidates=["claude-3-5-haiku-latest", "claude-3-5-sonnet-latest"],
            api_key_transport="header",
            api_key_header="x-api-key",
            api_key_prefix="",
        ),
        ValidationApiProfile(
            name="google_compat",
            api_format="google",
            base_url="https://generativelanguage.googleapis.com",
            path="/v1beta/models/{model}:generateContent",
            method="POST",
            headers={"Content-Type": "application/json"},
            model_candidates=["gemini-2.0-flash", "gemini-2.0-flash-lite"],
            api_key_transport="query",
            api_key_query_param="key",
        ),
    ]


def default_config() -> AppConfig:
    config = AppConfig(
        channels=default_channels(), validation_profiles=default_validation_profiles()
    )
    config.web.password_hash = hash_password("admin")
    config.api.token = hash_password("please-change-api-token")
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
            cfg.validation.revalidation_interval_seconds = int(
                validation_data.get(
                    "revalidation_interval_seconds",
                    cfg.validation.revalidation_interval_seconds,
                )
            )
            cfg.validation.pending_batch_size = int(
                validation_data.get(
                    "pending_batch_size", cfg.validation.pending_batch_size
                )
            )
            cfg.validation.validated_sample_size = int(
                validation_data.get(
                    "validated_sample_size", cfg.validation.validated_sample_size
                )
            )
            cfg.validation.ping_prompt = str(
                validation_data.get("ping_prompt", cfg.validation.ping_prompt)
            )
            cfg.validation.delete_invalid_keys = bool(
                validation_data.get(
                    "delete_invalid_keys", cfg.validation.delete_invalid_keys
                )
            )

            profiles_data = validation_data.get("profiles", [])
            profiles: list[ValidationApiProfile] = []
            if isinstance(profiles_data, list):
                for item in profiles_data:
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("name", "")).strip()
                    api_format = str(item.get("api_format", "")).strip().lower()
                    base_url = str(item.get("base_url", "")).strip()
                    path = str(item.get("path", "")).strip()
                    if not (name and api_format and base_url and path):
                        continue
                    headers_raw = item.get("headers", {})
                    headers = (
                        {str(k): str(v) for k, v in headers_raw.items()}
                        if isinstance(headers_raw, dict)
                        else {}
                    )
                    model_candidates_raw = item.get("model_candidates", [])
                    model_candidates = (
                        [str(x).strip() for x in model_candidates_raw if str(x).strip()]
                        if isinstance(model_candidates_raw, list)
                        else []
                    )
                    profiles.append(
                        ValidationApiProfile(
                            name=name,
                            api_format=api_format,
                            base_url=base_url,
                            path=path,
                            method=str(item.get("method", "POST")).strip().upper()
                            or "POST",
                            headers=headers,
                            model_candidates=model_candidates,
                            api_key_transport=str(
                                item.get("api_key_transport", "header")
                            )
                            .strip()
                            .lower()
                            or "header",
                            api_key_header=str(
                                item.get("api_key_header", "Authorization")
                            ),
                            api_key_prefix=str(item.get("api_key_prefix", "Bearer ")),
                            api_key_query_param=str(
                                item.get("api_key_query_param", "key")
                            ),
                            enabled=bool(item.get("enabled", True)),
                        )
                    )
            if profiles:
                cfg.validation_profiles = profiles

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
                        validation_profile=str(
                            item.get("validation_profile", "openai_compat")
                        ).strip()
                        or "openai_compat",
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
