from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any

import requests

from app.config import ValidationConfig


@dataclass(slots=True)
class ValidationResult:
    status: str
    detail: str


def _provider_request(provider: str, api_key: str) -> tuple[str, str, dict[str, str], dict[str, Any] | None]:
    provider_l = provider.lower()
    headers: dict[str, str] = {"User-Agent": "github-llm-key-searcher/1.0"}
    body: dict[str, Any] | None = None

    if provider_l == "openai":
        headers["Authorization"] = f"Bearer {api_key}"
        return "GET", "https://api.openai.com/v1/models", headers, body
    if provider_l == "anthropic":
        headers["x-api-key"] = api_key
        headers["anthropic-version"] = "2023-06-01"
        headers["Content-Type"] = "application/json"
        body = {"model": "claude-3-haiku-20240307", "max_tokens": 1, "messages": [{"role": "user", "content": "validate"}]}
        return "POST", "https://api.anthropic.com/v1/messages", headers, body
    if provider_l == "google":
        return "GET", f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}", headers, body
    if provider_l == "openrouter":
        headers["Authorization"] = f"Bearer {api_key}"
        return "GET", "https://openrouter.ai/api/v1/key", headers, body
    if provider_l == "mistral":
        headers["Authorization"] = f"Bearer {api_key}"
        return "GET", "https://api.mistral.ai/v1/models", headers, body
    if provider_l == "deepseek":
        headers["Authorization"] = f"Bearer {api_key}"
        return "GET", "https://api.deepseek.com/models", headers, body
    if provider_l == "groq":
        headers["Authorization"] = f"Bearer {api_key}"
        return "GET", "https://api.groq.com/openai/v1/models", headers, body
    if provider_l == "xai":
        headers["Authorization"] = f"Bearer {api_key}"
        return "GET", "https://api.x.ai/v1/models", headers, body
    return "GET", "", headers, body


class Validator:
    def __init__(self, config: ValidationConfig) -> None:
        self.config = config

    def validate(self, provider: str, api_key: str, proxy: str = "") -> ValidationResult:
        method, url, headers, body = _provider_request(provider, api_key)
        if not url:
            return ValidationResult(status="UNKNOWN_PROVIDER", detail="provider is not supported")

        proxies = {"http": proxy, "https": proxy} if proxy.strip() else None

        for attempt in range(self.config.retries + 1):
            try:
                response = requests.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=body,
                    timeout=self.config.request_timeout_seconds,
                    proxies=proxies,
                )
            except requests.RequestException as exc:
                if attempt >= self.config.retries:
                    return ValidationResult(status="NETWORK_ERROR", detail=str(exc))
                time.sleep(self.config.initial_backoff_seconds * (2**attempt))
                continue

            if response.status_code == 200:
                return ValidationResult(status="VALID", detail="key is valid")
            if response.status_code == 402 and provider.lower() == "openrouter":
                return ValidationResult(status="QUOTA_EXCEEDED", detail="valid key but no credits")
            if response.status_code in (401, 403):
                return ValidationResult(status="INVALID", detail=f"auth failed ({response.status_code})")
            if response.status_code == 429:
                if attempt >= self.config.retries:
                    return ValidationResult(status="RATE_LIMITED", detail="rate limited")
                time.sleep(self.config.initial_backoff_seconds * (2**attempt))
                continue
            return ValidationResult(status="ERROR", detail=f"unexpected status {response.status_code}")
        return ValidationResult(status="ERROR", detail="unknown error")
