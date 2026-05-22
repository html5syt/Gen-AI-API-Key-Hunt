from __future__ import annotations

from dataclasses import dataclass
import re
import time
import urllib.parse
from typing import Callable

import requests

from app.config import ChannelConfig, GithubConfig


@dataclass(slots=True)
class Candidate:
    channel_name: str
    provider: str
    api_key: str
    repository: str
    file_path: str
    file_url: str
    matched_line: str


class GitHubSearcher:
    def __init__(self, github_config: GithubConfig) -> None:
        self.github_config = github_config

    def _headers(self, token: str) -> dict[str, str]:
        return {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3.text-match+json",
            "User-Agent": self.github_config.user_agent,
        }

    def run_channel(
        self,
        channel: ChannelConfig,
        emit: Callable[[Candidate], None],
        should_stop: Callable[[], bool],
    ) -> int:
        if not channel.enabled:
            return 0
        if not self.github_config.tokens:
            return 0

        tokens = self.github_config.tokens
        token_index = 0
        found = 0
        compiled = [re.compile(pattern) for pattern in channel.extract_patterns]
        query = urllib.parse.quote(channel.query)
        proxy_map = {"http": channel.proxy, "https": channel.proxy} if channel.proxy.strip() else None

        for page in range(1, self.github_config.max_pages + 1):
            if should_stop():
                break
            url = f"https://api.github.com/search/code?q={query}&per_page=100&page={page}"
            token = tokens[token_index % len(tokens)]
            token_index += 1

            try:
                response = requests.get(
                    url,
                    headers=self._headers(token),
                    timeout=self.github_config.request_timeout_seconds,
                    proxies=proxy_map,
                )
            except requests.RequestException:
                continue

            if response.status_code == 403:
                time.sleep(1)
                continue
            if response.status_code != 200:
                break

            payload = response.json()
            items = payload.get("items", [])
            if not isinstance(items, list) or not items:
                break

            for item in items:
                if not isinstance(item, dict):
                    continue
                repository = ""
                repo_obj = item.get("repository")
                if isinstance(repo_obj, dict):
                    repository = str(repo_obj.get("full_name", ""))
                file_path = str(item.get("path", ""))
                file_url = str(item.get("html_url", ""))
                text_matches = item.get("text_matches", [])
                matched_line = ""
                if isinstance(text_matches, list) and text_matches:
                    first = text_matches[0]
                    if isinstance(first, dict):
                        matched_line = str(first.get("fragment", ""))

                if not matched_line:
                    continue

                for pattern in compiled:
                    matches = pattern.findall(matched_line)
                    for match in matches:
                        api_key = match if isinstance(match, str) else str(match)
                        emit(
                            Candidate(
                                channel_name=channel.name,
                                provider=channel.provider,
                                api_key=api_key,
                                repository=repository,
                                file_path=file_path,
                                file_url=file_url,
                                matched_line=matched_line,
                            )
                        )
                        found += 1
            if len(items) < 100:
                break
            time.sleep(self.github_config.page_delay_seconds)
        return found
