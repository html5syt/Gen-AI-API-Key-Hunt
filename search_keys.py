import requests
import time
import urllib.parse
import os
import sqlite3
from sqlite3 import Connection
from typing import Dict, Iterable, List, Optional, Tuple

try:
    # Optional: load environment variables from a .env file if present
    from dotenv import load_dotenv  # type: ignore

    load_dotenv()
except ImportError:
    # Safe fallback if python-dotenv is not installed
    # Intentionally ignore missing dependency and continue.
    ...

def init_database(db_path: str) -> Connection:
    """Initialize SQLite database and create results table if not present."""
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS results (
            id INTEGER PRIMARY KEY,
            search_query TEXT,
            repository TEXT,
            file_path TEXT,
            file_url TEXT,
            matched_line TEXT,
            UNIQUE(repository, file_path)
        )
    """)
    con.commit()
    return con


def insert_result(con: Connection, result: Dict[str, Optional[str]]) -> None:
    """Insert a single search result into the database, ignoring duplicates."""
    cur = con.cursor()
    cur.execute("""
        INSERT OR IGNORE INTO results (search_query, repository, file_path, file_url, matched_line)
        VALUES (?, ?, ?, ?, ?)
    """, (
        result["search_query"],
        result["repository"],
        result["file_path"],
        result["file_url"],
        result["matched_line"],
    ))
    con.commit()


def load_github_tokens() -> List[str]:
    """Load GitHub tokens from env var `GITHUB_TOKENS` or fallback to `GITHUB_TOKEN`.

    `GITHUB_TOKENS` should be a comma-separated list. If absent, tries
    `GITHUB_TOKEN`. Returns only non-empty tokens.
    """
    raw_multi = os.getenv("GITHUB_TOKENS", "")
    if raw_multi.strip():
        return [t.strip() for t in raw_multi.split(",") if t.strip()]

    single = os.getenv("GITHUB_TOKEN", "")
    return [single] if single.strip() else []


def _user_agent() -> str:
    """Return User-Agent header value (configurable via GITHUB_USER_AGENT)."""
    return os.getenv("GITHUB_USER_AGENT", "api-key-hunt/1.0")


def make_api_headers(token: str) -> Dict[str, str]:
    """Headers for GitHub REST API calls."""
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3.text-match+json",
        "User-Agent": _user_agent(),
    }


class _NoTokenAvailable(Exception):
    """Raised when no GitHub tokens are currently available."""


def _parse_rate_limit_headers(resp: requests.Response) -> Tuple[Optional[int], Optional[int]]:
    """Parse GitHub rate limit headers to (remaining, reset_epoch)."""
    remaining_hdr = resp.headers.get("X-RateLimit-Remaining")
    reset_hdr = resp.headers.get("X-RateLimit-Reset")
    remaining = int(remaining_hdr) if remaining_hdr and remaining_hdr.isdigit() else None
    reset_epoch = int(reset_hdr) if reset_hdr and reset_hdr.isdigit() else None
    return remaining, reset_epoch


def _parse_retry_after_seconds(resp: requests.Response) -> Optional[int]:
    """Parse Retry-After header (seconds). Returns None if absent/invalid."""
    value = resp.headers.get("Retry-After")
    if not value:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _get_int_env(name: str, default: int) -> int:
    """Read integer environment variable with a default."""
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except Exception:
        return default


# Tunables via env vars
REQUEST_TIMEOUT_SECONDS: int = _get_int_env("REQUEST_TIMEOUT_SECONDS", 10)
PAGE_DELAY_SECONDS: int = _get_int_env("PAGE_DELAY_SECONDS", 2)
MAX_PAGES: int = _get_int_env("MAX_PAGES", 20)
DEFAULT_BACKOFF_SECONDS: int = _get_int_env("DEFAULT_BACKOFF_SECONDS", 60)
MAX_BACKOFF_SECONDS: int = _get_int_env("MAX_BACKOFF_SECONDS", 600)
RAW_FETCH_WORKERS: int = _get_int_env("RAW_FETCH_WORKERS", 8)


def _next_backoff_seconds(token: str, backoff_state: Dict[str, int]) -> int:
    """Return next backoff delay (exponential up to MAX_BACKOFF_SECONDS)."""
    prev = backoff_state.get(token, 0)
    if prev <= 0:
        delay = DEFAULT_BACKOFF_SECONDS
    else:
        delay = min(prev * 2, MAX_BACKOFF_SECONDS)
    backoff_state[token] = delay
    return delay


def _select_token(tokens: List[str], state: Dict[str, int]) -> str:
    """Select next token via round-robin, skipping cooling-down tokens.

    `state` maps token -> cooldown_until_epoch. `_rr_idx` is the round-robin index.
    """
    if not tokens:
        raise _NoTokenAvailable("No tokens configured")

    now = int(time.time())
    start_idx = state.get("_rr_idx", 0) % len(tokens)
    for i in range(len(tokens)):
        idx = (start_idx + i) % len(tokens)
        token = tokens[idx]
        if state.get(token, 0) <= now:
            state["_rr_idx"] = (idx + 1) % len(tokens)
            return token
    raise _NoTokenAvailable("All tokens are cooling down")


def _mark_token_cooldown(token: str, state: Dict[str, int], reset_epoch: Optional[int]) -> None:
    """Mark a token to cooldown until reset epoch (or short backoff)."""
    now = int(time.time())
    until = reset_epoch if reset_epoch and reset_epoch > now else now + 60
    state[token] = until

CHARSET: str = (
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789-_"
)


def expand_prefix_variants(prefix: str, charset: str, require_char: bool = False) -> List[str]:
    """Build list of prefix variants to bypass 1000 results limit.

    If require_char is False, include the raw prefix and prefix+<ch> for each char.
    If require_char is True, include only prefix+<ch> for each char.
    """
    variants: List[str] = []
    if not require_char:
        variants.append(prefix)
    for ch in charset:
        variants.append(f"{prefix}{ch}")
    return variants


def build_provider_queries(
    variable_names: Iterable[str],
    key_prefixes: Iterable[str],
    expand_first_char: bool = True,
    require_char_for_prefix: bool = False,
) -> List[str]:
    """Construct search queries for all variable/prefix permutations.

    - variable_names: env variable name variants (e.g., OPENAI_API_KEY, OPENAI_KEY)
    - key_prefixes: token prefixes (e.g., sk-, sk-proj-, AIza)
    - expand_first_char: whether to append first char variants
    - require_char_for_prefix: omit raw prefix (used when there is no fixed prefix)
    """
    queries_local: List[str] = []
    for var in variable_names:
        for pref in key_prefixes:
            pref_variants = (
                expand_prefix_variants(pref, CHARSET, require_char_for_prefix)
                if expand_first_char
                else [pref]
            )
            for pv in pref_variants:
                queries_local.append(f"{var}={pv}")
    return queries_local


def generate_all_queries() -> List[str]:
    """Generate a comprehensive list of search queries across providers.

    Covers multiple env var spellings and token prefixes, and expands the
    first character to circumvent GitHub Search 1000-results windows.
    """
    all_q: List[str] = []

    # OpenAI
    openai_vars: List[str] = [
        "OPENAI_API_KEY",
        "OPENAI_KEY",
        "OPENAI_SECRET_KEY",
        "OPENAI_TOKEN",
    ]
    openai_prefixes: List[str] = ["sk-", "sk-proj-"]
    all_q += build_provider_queries(openai_vars, openai_prefixes, True, False)

    # Anthropic / Claude
    anthropic_vars: List[str] = [
        "ANTHROPIC_API_KEY",
        "CLAUDE_API_KEY",
        "ANTHROPIC_KEY",
    ]
    anthropic_prefixes: List[str] = ["sk-ant-", "sk-ant-api03-", "apikey_"]
    all_q += build_provider_queries(anthropic_vars, anthropic_prefixes, True, False)

    # Google / Gemini
    google_vars: List[str] = ["GOOGLE_API_KEY", "GEMINI_API_KEY", "GEMINI_KEY"]
    google_prefixes: List[str] = ["AIzaSy"]
    all_q += build_provider_queries(google_vars, google_prefixes, True, False)

    # OpenRouter
    openrouter_vars: List[str] = ["OPENROUTER_API_KEY", "OPEN_ROUTER_API_KEY"]
    openrouter_prefixes: List[str] = ["sk-or-v1-"]
    all_q += build_provider_queries(openrouter_vars, openrouter_prefixes, True, False)

    # Mistral (no fixed public prefix, expand by first char only)
    mistral_vars: List[str] = ["MISTRAL_API_KEY", "MISTRAL_KEY"]
    mistral_prefixes: List[str] = [""]
    all_q += build_provider_queries(
        mistral_vars, mistral_prefixes, True, True
    )

    # DeepSeek
    deepseek_vars: List[str] = ["DEEPSEEK_API_KEY", "DEEPSEEK_KEY"]
    deepseek_prefixes: List[str] = ["sk-"]
    all_q += build_provider_queries(deepseek_vars, deepseek_prefixes, True, False)

    # Grok (xAI-older) and Groq
    grok_vars: List[str] = ["GROK_API_KEY", "GROK_KEY"]
    grok_prefixes: List[str] = ["gsk_"]
    all_q += build_provider_queries(grok_vars, grok_prefixes, True, False)

    groq_vars: List[str] = ["GROQ_API_KEY", "GROQ_KEY"]
    groq_prefixes: List[str] = ["gsk_"]
    all_q += build_provider_queries(groq_vars, groq_prefixes, True, False)

    # xAI
    xai_vars: List[str] = ["XAI_API_KEY", "XAI_KEY"]
    xai_prefixes: List[str] = ["xai-"]
    all_q += build_provider_queries(xai_vars, xai_prefixes, True, False)

    return all_q


# Generated queries covering multiple variable spellings and
# first-character expansions to bypass GitHub Search result caps.
queries: List[str] = generate_all_queries()


def github_search(con: Connection, query: str, per_page: int = 50) -> int:
    """Run a GitHub code search and save results to the database.

    Supports multiple tokens via env `GITHUB_TOKENS` with round-robin rotation
    and per-token cooldown based on GitHub rate limit headers.

    Returns the number of new items inserted into the database.
    """
    url = f"https://api.github.com/search/code?q={urllib.parse.quote(query)}&per_page={per_page}"
    items_found = 0
    page = 1
    tokens: List[str] = load_github_tokens()
    token_state: Dict[str, int] = {}
    backoff_state: Dict[str, int] = {}

    while True:
        paged_url = f"{url}&page={page}"

        # Pick token
        while True:
            try:
                token = _select_token(tokens, token_state)
                break
            except _NoTokenAvailable:
                if not token_state:
                    raise
                earliest = min(token_state.values())
                sleep_for = max(1, earliest - int(time.time()))
                print(f"All tokens limited. Sleeping {sleep_for}s...")
                time.sleep(sleep_for)

        try:
            r = requests.get(paged_url, headers=make_api_headers(token), timeout=REQUEST_TIMEOUT_SECONDS)
        except requests.exceptions.RequestException as e:
            print(f"Request failed: {e}. Cooling down token and retrying.")
            # Use exponential backoff for the token
            backoff = _next_backoff_seconds(token, backoff_state)
            _mark_token_cooldown(token, token_state, int(time.time()) + backoff)
            continue

        remaining, reset_epoch = _parse_rate_limit_headers(r)
        if remaining is not None and remaining <= 0:
            _mark_token_cooldown(token, token_state, reset_epoch)
        if r.status_code != 200:
            if r.status_code == 403:
                retry_after = _parse_retry_after_seconds(r)
                if retry_after is not None:
                    _mark_token_cooldown(token, token_state, int(time.time()) + retry_after)
                elif reset_epoch is not None:
                    _mark_token_cooldown(token, token_state, reset_epoch)
                else:
                    # No headers available: exponential backoff
                    backoff = _next_backoff_seconds(token, backoff_state)
                    _mark_token_cooldown(token, token_state, int(time.time()) + backoff)
                print(f"Rate limited (403). Cooling down current token and retrying page {page} with another token...")
                # Retry loop by continuing without advancing page
                continue
            print(f"Error: {r.status_code}, {r.text}")
            break

        data = r.json()
        items = data.get("items", [])
        if not items:
            break

        for item in items:
            repo_name = item["repository"]["full_name"]
            file_path = item["path"]
            file_url = item["html_url"]

            # Extract matched line from text_matches if available
            text_matches = item.get("text_matches", [])
            matched_line = text_matches[0]["fragment"] if text_matches else None

            result_item = {
                "search_query": query,
                "repository": repo_name,
                "file_path": file_path,
                "file_url": file_url,
                "matched_line": matched_line.strip() if matched_line else None,
            }
            insert_result(con, result_item)
            items_found += 1

        if len(items) < per_page or page >= MAX_PAGES:
            break

        page += 1
        time.sleep(PAGE_DELAY_SECONDS)

    return items_found


def _parse_query(query: str) -> Tuple[str, str]:
    """Split query of form "VAR=VALUE_PREFIX" into parts.

    Returns (variable_name, value_prefix). If '=' is missing, treats entire
    string as variable_name and value_prefix as empty string.
    """
    if "=" in query:
        var, val = query.split("=", 1)
        return var, val
    return query, ""


def _probe_total_count(query: str) -> Optional[int]:
    """Probe GitHub Search API to get total_count for a query.

    Uses a lightweight request (per_page=1) and honors token rotation and
    cooldowns similarly to the main search. Returns None on non-200 errors.
    """
    base_url = f"https://api.github.com/search/code?q={urllib.parse.quote(query)}&per_page=1&page=1"

    tokens: List[str] = load_github_tokens()
    token_state: Dict[str, int] = {}
    backoff_state: Dict[str, int] = {}

    while True:
        # Select a token respecting cooldowns
        while True:
            try:
                token = _select_token(tokens, token_state)
                break
            except _NoTokenAvailable:
                if not token_state:
                    return None
                earliest = min(token_state.values())
                sleep_for = max(1, earliest - int(time.time()))
                print(f"All tokens limited (probe). Sleeping {sleep_for}s...")
                time.sleep(sleep_for)

        try:
            r = requests.get(base_url, headers=make_api_headers(token), timeout=REQUEST_TIMEOUT_SECONDS)
        except requests.exceptions.RequestException as e:
            print(f"Probe request failed: {e}. Cooling down token and retrying.")
            backoff = _next_backoff_seconds(token, backoff_state)
            _mark_token_cooldown(token, token_state, int(time.time()) + backoff)
            continue

        remaining, reset_epoch = _parse_rate_limit_headers(r)
        if remaining is not None and remaining <= 0:
            _mark_token_cooldown(token, token_state, reset_epoch)

        if r.status_code != 200:
            if r.status_code == 403:
                retry_after = _parse_retry_after_seconds(r)
                if retry_after is not None:
                    _mark_token_cooldown(token, token_state, int(time.time()) + retry_after)
                elif reset_epoch is not None:
                    _mark_token_cooldown(token, token_state, reset_epoch)
                else:
                    backoff = _next_backoff_seconds(token, backoff_state)
                    _mark_token_cooldown(token, token_state, int(time.time()) + backoff)
                # Break inner token selection loop to try another token
                break
            return None

        try:
            data = r.json()
            return int(data.get("total_count", 0))
        except Exception:
            return None

    # Safety return to satisfy static analyzers in case the loop exits unexpectedly
    return None


def _adaptive_collect(con: Connection, var_name: str, value_prefix: str, max_depth: int, depth: int) -> int:
    """Recursively collect results, expanding by one character when capped at 1000.

    - If total_count < 1000 for current query, run full paginated search and return.
    - If total_count >= 1000 and depth < max_depth, branch into next-character variants.
    - If total_count >= 1000 and depth == max_depth, still run full search (best effort).
    """
    query = f"{var_name}={value_prefix}"
    total = _probe_total_count(query)

    if total is None:
        # Fallback to full search if probing failed
        return github_search(con, query)

    if total < 1000:
        return github_search(con, query)

    if depth >= max_depth:
        # At max depth, accept possible truncation and collect
        print(f"Query capped at 1000 at depth {depth}: {query} (collecting anyway)")
        return github_search(con, query)

    # Branch by adding one more character and recurse
    total_found = 0
    for ch in CHARSET:
        child_prefix = f"{value_prefix}{ch}"
        total_found += _adaptive_collect(con, var_name, child_prefix, max_depth, depth + 1)
    return total_found


def adaptive_search(con: Connection, query: str, max_depth: int = 2) -> int:
    """Adaptive search that deepens prefix expansion up to two characters.

    The function detects when a query hits GitHub's 1000-result cap and, in
    that case, recursively expands the search by appending next characters
    from CHARSET up to `max_depth` (default 2 characters after the base
    prefix). This helps partition results into smaller windows.
    """
    var_name, value_prefix = _parse_query(query)
    return _adaptive_collect(con, var_name, value_prefix, max_depth=max_depth, depth=0)


if __name__ == "__main__":
    db_file = "api_keys.db"
    db_connection = init_database(db_file)
    total_found_count = 0

    try:
        for q in queries:
            print(f"Searching (adaptive) for: {q}")
            found_count = adaptive_search(db_connection, q, max_depth=2)
            total_found_count += found_count
            print(f"  -> Found {found_count} new items (total: {total_found_count})")

        print(f"Done. Results saved to {db_file}")
    except KeyboardInterrupt:
        print(f"Interrupted. Partial results saved to {db_file}")
    except Exception as e:
        print(f"An error occurred: {e}")
        raise
    finally:
        db_connection.close()
