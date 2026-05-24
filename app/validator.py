from __future__ import annotations

from dataclasses import dataclass
import secrets
import time
from typing import Any
from urllib.parse import urljoin

import requests

from app.config import AppConfig, ChannelConfig


@dataclass(slots=True)
class ValidationResult:
    status: str
    detail: str


class Validator:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def _channel_config(self, channel_name: str, provider: str) -> ChannelConfig | None:
        for channel in self.config.channels:
            if channel.name == channel_name or channel.provider == provider:
                return channel
        return None

    def _build_url(self, channel: ChannelConfig, model: str) -> str:
        base_url = channel.base_url.rstrip("/")
        path = channel.path.format(model=model)
        if not path.startswith("/"):
            path = f"/{path}"
        return f"{base_url}{path}"

    def _model_list_path(self, channel: ChannelConfig) -> str:
        path = channel.path.strip()
        if channel.api_format == "google":
            return "/v1beta/models"
        if "{model}" in path:
            prefix = path.split("{model}", 1)[0].rstrip("/")
            return prefix if prefix.endswith("/models") else f"{prefix}/models"
        for suffix in ("/chat/completions", "/messages"):
            if suffix in path:
                return f"{path.split(suffix, 1)[0].rstrip('/')}/models"
        return f"{path.rstrip('/')}/models"

    def _build_headers(self, channel: ChannelConfig, api_key: str) -> dict[str, str]:
        headers = dict(channel.headers)
        if channel.api_key_transport == "header":
            headers[channel.api_key_header] = f"{channel.api_key_prefix}{api_key}"
        return headers

    def _build_params(
        self, channel: ChannelConfig, api_key: str
    ) -> dict[str, str] | None:
        if channel.api_key_transport == "query":
            return {channel.api_key_query_param: api_key}
        return None

    def _extract_model_names(self, payload: Any) -> list[str]:
        items: list[Any] = []
        if isinstance(payload, dict):
            for key in ("data", "models", "items"):
                value = payload.get(key)
                if isinstance(value, list):
                    items.extend(value)
            if not items and any(key in payload for key in ("id", "name", "model")):
                items.append(payload)
        elif isinstance(payload, list):
            items.extend(payload)

        names: list[str] = []
        for item in items:
            if isinstance(item, str):
                candidate = item.strip()
            elif isinstance(item, dict):
                candidate = ""
                for key in ("id", "name", "model", "slug"):
                    value = str(item.get(key, "")).strip()
                    if value:
                        candidate = value
                        break
            else:
                candidate = ""
            if candidate and candidate not in names:
                names.append(candidate)
        return names

    def _fetch_models(self, channel: ChannelConfig, api_key: str) -> list[str]:
        base_url = channel.base_url.rstrip("/")
        model_list_url = urljoin(f"{base_url}/", self._model_list_path(channel).lstrip("/"))
        headers = self._build_headers(channel, api_key)
        params = self._build_params(channel, api_key)
        try:
            response = requests.request(
                method="GET",
                url=model_list_url,
                headers=headers,
                params=params,
                timeout=self.config.validation.request_timeout_seconds,
            )
        except requests.RequestException:
            return []

        if response.status_code not in {200, 201}:
            return []

        try:
            payload = response.json()
        except ValueError:
            return []

        return self._extract_model_names(payload)

    def _build_body(self, channel: ChannelConfig, model: str) -> dict[str, Any]:
        prompt = self.config.validation.ping_prompt
        if channel.api_format == "anthropic":
            return {
                "model": model,
                "max_tokens": 1,
                "messages": [{"role": "user", "content": prompt}],
            }
        if channel.api_format == "google":
            return {
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"maxOutputTokens": 1},
            }
        return {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 1,
            "temperature": 0,
        }

    def _extract_text(self, channel: ChannelConfig, payload: Any) -> str:
        if not isinstance(payload, dict):
            return ""

        if channel.api_format == "anthropic":
            content = payload.get("content", [])
            if isinstance(content, list):
                fragments = []
                for item in content:
                    if isinstance(item, dict):
                        text = item.get("text", "")
                        if text:
                            fragments.append(str(text))
                return "\n".join(fragments).strip()
            return ""

        if channel.api_format == "google":
            candidates = payload.get("candidates", [])
            if isinstance(candidates, list) and candidates:
                first = candidates[0]
                if isinstance(first, dict):
                    content = first.get("content", {})
                    if isinstance(content, dict):
                        parts = content.get("parts", [])
                        if isinstance(parts, list):
                            fragments = []
                            for item in parts:
                                if isinstance(item, dict):
                                    text = item.get("text", "")
                                    if text:
                                        fragments.append(str(text))
                            return "\n".join(fragments).strip()
            return str(payload.get("text", "")).strip()

        choices = payload.get("choices", [])
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                message = first.get("message", {})
                if isinstance(message, dict):
                    text = message.get("content", "")
                    if isinstance(text, list):
                        fragments = []
                        for item in text:
                            if isinstance(item, dict):
                                value = item.get("text", "")
                                if value:
                                    fragments.append(str(value))
                        return "\n".join(fragments).strip()
                    if text:
                        return str(text).strip()
                text = first.get("text", "")
                if text:
                    return str(text).strip()

        if "output_text" in payload:
            return str(payload.get("output_text", "")).strip()
        return str(payload.get("text", "")).strip()

    def _has_meaningful_text(self, content: str) -> bool:
        if not content:
            return False
        return any(char.isalnum() for char in content)

    def _is_insufficient_balance(self, text: str) -> bool:
        lowered = text.lower()
        return any(
            key in lowered
            for key in (
                "insufficient balance",
                "insufficient credits",
                "insufficient credit",
                "insufficient funds",
                "quota exceeded",
                "no credits",
                "out of credits",
                "billing",
            )
        )

    def validate(
        self, channel_name: str, provider: str, api_key: str, proxy: str = ""
    ) -> ValidationResult:
        channel = self._channel_config(channel_name, provider)
        if channel is None:
            return ValidationResult(
                status="UNKNOWN_PROFILE", detail="channel is not supported"
            )

        proxies = {"http": proxy, "https": proxy} if proxy.strip() else None
        available_models = self._fetch_models(channel, api_key) or channel.model_candidates
        if not available_models:
            return ValidationResult(
                status="ERROR",
                detail=f"channel {channel.name} returned no models",
            )

        for attempt in range(self.config.validation.retries + 1):
            model = secrets.choice(available_models)
            url = self._build_url(channel, model)
            headers = self._build_headers(channel, api_key)
            params = self._build_params(channel, api_key)
            body = self._build_body(channel, model)

            try:
                response = requests.request(
                    method=channel.method,
                    url=url,
                    headers=headers,
                    params=params,
                    json=body,
                    timeout=self.config.validation.request_timeout_seconds,
                    proxies=proxies,
                )
            except requests.RequestException as exc:
                if attempt >= self.config.validation.retries:
                    return ValidationResult(status="NETWORK_ERROR", detail=str(exc))
                time.sleep(
                    self.config.validation.initial_backoff_seconds * (2**attempt)
                )
                continue

            if response.status_code in {401, 403}:
                return ValidationResult(
                    status="INVALID", detail=f"auth failed ({response.status_code})"
                )
            if response.status_code == 402:
                return ValidationResult(
                    status="INVALID", detail="insufficient balance (402)"
                )
            if response.status_code == 429:
                if attempt >= self.config.validation.retries:
                    return ValidationResult(status="RATE_LIMITED", detail="rate limited")
                time.sleep(
                    self.config.validation.initial_backoff_seconds * (2**attempt)
                )
                continue
            if response.status_code < 200 or response.status_code >= 300:
                return ValidationResult(
                    status="ERROR", detail=f"unexpected status {response.status_code}"
                )

            try:
                payload = response.json()
            except ValueError:
                payload = {"text": response.text}

            if isinstance(payload, dict) and "error" in payload:
                error_blob = payload.get("error")
                error_text = ""
                if isinstance(error_blob, dict):
                    error_text = str(error_blob.get("message", ""))
                else:
                    error_text = str(error_blob)
                if error_text:
                    if self._is_insufficient_balance(error_text):
                        return ValidationResult(status="INVALID", detail=error_text)
                    return ValidationResult(status="ERROR", detail=error_text)

            content = self._extract_text(channel, payload)
            if not self._has_meaningful_text(content):
                detail_text = content.strip() or "empty response"
                if self._is_insufficient_balance(detail_text):
                    return ValidationResult(status="INVALID", detail=detail_text)
                return ValidationResult(
                    status="INVALID",
                    detail="response did not contain meaningful content",
                )
            if self._is_insufficient_balance(content):
                return ValidationResult(status="INVALID", detail=content.strip())
            return ValidationResult(
                status="VALID", detail="ping-pong response contained meaningful content"
            )

        return ValidationResult(status="ERROR", detail="unknown error")
