from __future__ import annotations

from dataclasses import dataclass
import secrets
import time
from typing import Any

import requests

from app.config import AppConfig, ValidationApiProfile


@dataclass(slots=True)
class ValidationResult:
    status: str
    detail: str


class Validator:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def _channel_profile_name(self, channel_name: str, provider: str) -> str:
        for channel in self.config.channels:
            if channel.name == channel_name or channel.provider == provider:
                profile_name = channel.validation_profile.strip()
                if profile_name:
                    return profile_name
        return "openai_compat"

    def _profile_for(
        self, channel_name: str, provider: str
    ) -> ValidationApiProfile | None:
        profile_name = self._channel_profile_name(channel_name, provider)
        for profile in self.config.validation_profiles:
            if profile.enabled and profile.name == profile_name:
                return profile
        return None

    def _build_url(self, profile: ValidationApiProfile, model: str) -> str:
        base_url = profile.base_url.rstrip("/")
        path = profile.path.format(model=model)
        if not path.startswith("/"):
            path = f"/{path}"
        return f"{base_url}{path}"

    def _build_headers(
        self, profile: ValidationApiProfile, api_key: str
    ) -> dict[str, str]:
        headers = dict(profile.headers)
        if profile.api_key_transport == "header":
            headers[profile.api_key_header] = f"{profile.api_key_prefix}{api_key}"
        return headers

    def _build_params(
        self, profile: ValidationApiProfile, api_key: str
    ) -> dict[str, str] | None:
        if profile.api_key_transport == "query":
            return {profile.api_key_query_param: api_key}
        return None

    def _build_body(self, profile: ValidationApiProfile, model: str) -> dict[str, Any]:
        prompt = self.config.validation.ping_prompt
        if profile.api_format == "anthropic":
            return {
                "model": model,
                "max_tokens": 1,
                "messages": [{"role": "user", "content": prompt}],
            }
        if profile.api_format == "google":
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

    def _extract_text(self, profile: ValidationApiProfile, payload: Any) -> str:
        if not isinstance(payload, dict):
            return ""

        if profile.api_format == "anthropic":
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

        if profile.api_format == "google":
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
        profile = self._profile_for(channel_name, provider)
        if profile is None:
            return ValidationResult(
                status="UNKNOWN_PROFILE", detail="validation profile is not supported"
            )
        if not profile.model_candidates:
            return ValidationResult(
                status="ERROR",
                detail=f"validation profile {profile.name} has no models",
            )

        proxies = {"http": proxy, "https": proxy} if proxy.strip() else None

        for attempt in range(self.config.validation.retries + 1):
            model = secrets.choice(profile.model_candidates)
            url = self._build_url(profile, model)
            headers = self._build_headers(profile, api_key)
            params = self._build_params(profile, api_key)
            body = self._build_body(profile, model)

            try:
                response = requests.request(
                    method=profile.method,
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

            content = self._extract_text(profile, payload)
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
