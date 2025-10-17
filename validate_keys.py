import sqlite3
import re
import asyncio
import aiohttp 
import threading
from typing import List, Set, Dict, Any, Tuple
from datetime import datetime
import concurrent.futures
from aiohttp import ClientTimeout


CANDIDATES_DB_PATH = "4_api_keys.db"
VALID_DB_PATH = "valid_api_keys.db"
MAX_CONCURRENT_REQUESTS = 20
MAX_RETRIES = 3
INITIAL_BACKOFF_DELAY = 1


PROVIDER_CONFIGS: Dict[str, Any] = {
    "openai": {
        "queries": [],
        "prefixes": ["sk-", "sk-proj-"],
        "patterns": [r'(sk-proj-[A-Za-z0-9\-_]{48,156})', r'(sk-[A-Za-z0-9]{48})'],
        "validation": {
            "url": "https://api.openai.com/v1/models",
            "method": "GET",
            "auth_header": "Authorization",
            "auth_scheme": "Bearer {}"
        }
    },
    "anthropic": {
        "queries": [],
        "prefixes": ["sk-ant-", "sk-ant-api03-", "apikey_"],
        "patterns": [r'(sk-ant-api03-[A-Za-z0-9\-_]{95})', r'(sk-ant-[A-Za-z0-9\-_]{44})'],
        "validation": {
            "url": "https://api.anthropic.com/v1/messages",
            "method": "POST",
            "auth_header": "x-api-key",
            "auth_scheme": "{}",
            "extra_headers": {'anthropic-version': '2023-06-01', 'Content-Type': 'application/json'},
            "body": {"model": "claude-3-haiku-20240307", "max_tokens": 1, "messages": [{"role": "user", "content": "Validate"}]}
        }
    },
    "google": {
        "queries": [],
        "prefixes": ["AIza"],
        "patterns": [r'(AIza[0-9A-Za-z\-_]{35})'],
        "validation": {
            "url": "https://generativelanguage.googleapis.com/v1beta/models",
            "method": "GET",
            "auth_method": "key_param"
        }
    },
    "openrouter": {
        "queries": [],
        "prefixes": ["sk-or-v1-"],
        "patterns": [r'(sk-or-v1-[a-f0-9]{64})'],
        "validation": {
            "url": "https://openrouter.ai/api/v1/key",
            "method": "GET",
            "auth_header": "Authorization",
            "auth_scheme": "Bearer {}"
        }
    },
    "mistral": {
        "queries": [],
        "prefixes": [],
        "patterns": [r'([A-Za-z0-9]{32})'],
        "validation": {
            "url": "https://api.mistral.ai/v1/models",
            "method": "GET",
            "auth_header": "Authorization",
            "auth_scheme": "Bearer {}"
        }
    },
    "deepseek": {
        "queries": [],
        "prefixes": ["sk-"],
        "patterns": [r'(sk-[a-f0-9]{32})'],
        "validation": {
            "url": "https://api.deepseek.com/models",
            "method": "GET",
            "auth_header": "Authorization",
            "auth_scheme": "Bearer {}"
        }
    },
    "groq": {
        "queries": [],
        "prefixes": ["gsk_"],
        "patterns": [r'(gsk_[A-Za-z0-9]{48})'],
        "validation": {
            "url": "https://api.groq.com/openai/v1/models",
            "method": "GET",
            "auth_header": "Authorization",
            "auth_scheme": "Bearer {}"
        }
    },
    "xai": {
        "queries": [],
        "prefixes": ["xai-"],
        "patterns": [r'(xai-[A-Za-z0-9]{64})'],
        "validation": {
            "url": "https://api.x.ai/v1/models",
            "method": "GET",
            "auth_header": "Authorization",
            "auth_scheme": "Bearer {}"
        }
    },
}


def init_database_valid(db_path: str) -> sqlite3.Connection:
    """Initialize SQLite database and create valid_keys table if not present."""
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS valid_keys (
            id INTEGER PRIMARY KEY,
            provider TEXT,
            api_key TEXT,
            validated_at TEXT,
            UNIQUE(provider, api_key)
        )
    """)
    con.commit()
    return con


def insert_valid_key(con: sqlite3.Connection, provider: str, api_key: str) -> None:
    """Insert a valid API key into the database, ignoring duplicates."""
    cur = con.cursor()
    validated_at = datetime.now().isoformat()
    cur.execute("""
        INSERT OR IGNORE INTO valid_keys (provider, api_key, validated_at)
        VALUES (?,?,?)
    """, (provider, api_key, validated_at))
    con.commit()


def get_candidates_from_db(queries: List[str], prefixes: List[str]) -> List[str]:
    """Retrieves potential API key candidates from the database based on queries and prefixes."""
    candidates = []
    try:
        with sqlite3.connect(CANDIDATES_DB_PATH) as con:
            cur = con.cursor()
            if not queries and not prefixes:
                # If there are no prefixes and queries, return all matched_line
                cur.execute("SELECT matched_line FROM results")
                rows = cur.fetchall()
                candidates = [row[0] for row in rows if row[0]]
            else:
                query_conditions = []
                params = []
                if queries:
                    query_conditions.append("(" + " OR ".join(["search_query LIKE?"] * len(queries)) + ")")
                    params.extend(queries)
                if prefixes:
                    query_conditions.append("(" + " OR ".join(["matched_line LIKE?"] * len(prefixes)) + ")")
                    like_patterns = [f"%{prefix}%" for prefix in prefixes]
                    params.extend(like_patterns)
                sql_query = "SELECT matched_line FROM results WHERE " + " AND ".join(query_conditions)
                cur.execute(sql_query, params)
                rows = cur.fetchall()
                candidates = [row[0] for row in rows if row[0]]
    except sqlite3.OperationalError as e:
        print(f"\nError reading from database: {e}")
    return candidates


def extract_api_keys(line: str, patterns: List[str]) -> List[str]:
    found_keys = []
    for pattern in patterns:
        matches = re.findall(pattern, line)
        if matches:
            found_keys.extend(matches)
    return found_keys


async def validate_key(session: aiohttp.ClientSession, provider: str, api_key: str) -> Tuple[str, str]:
    config = PROVIDER_CONFIGS.get(provider.lower())
    if not config or "validation" not in config:
        return 'UNKNOWN_PROVIDER', f"Provider '{provider}' not supported."

    val_config = config["validation"]
    headers = {"User-Agent": "api-key-validator/2.0"}
    url = val_config['url']
    method = val_config['method']
    body = val_config.get('body')

    auth_method = val_config.get("auth_method")
    if auth_method == "key_param":
        url = f"{url}?key={api_key}"
    else:
        headers[val_config['auth_header']] = val_config['auth_scheme'].format(api_key)

    if 'extra_headers' in val_config:
        headers.update(val_config['extra_headers'])

    for attempt in range(MAX_RETRIES + 1):
        try:
            async with session.request(method, url, headers=headers, json=body, timeout=ClientTimeout(total=15)) as response:
                if response.status == 200:
                    return 'VALID', 'Key is valid and active.'
                elif response.status in [401, 403]:
                    return 'INVALID', f'Authentication error (Code: {response.status})'
                elif response.status == 400 and provider.lower() == 'google':
                    error_text = await response.text()
                    if "API key not valid" in error_text:
                        return 'INVALID', f'Invalid key (Code: {response.status})'
                elif response.status == 402 and provider.lower() == 'openrouter':
                    return 'QUOTA_EXCEEDED', f'Valid key, but insufficient credits (Code: {response.status})'
                elif response.status == 429:
                    if attempt < MAX_RETRIES:
                        delay = INITIAL_BACKOFF_DELAY * (2 ** attempt)
                        await asyncio.sleep(delay)
                        continue
                    else:
                        return 'RATE_LIMIT_EXCEEDED', f'Rate limit exceeded after {MAX_RETRIES} retries.'
                else:
                    error_text = await response.text()
                    return 'ERROR', f'Unexpected response (Code: {response.status}): {error_text[:100]}'
        except aiohttp.ClientError as e:
            return 'NETWORK_ERROR', f'Network error: {e}'
        except asyncio.TimeoutError:
            return 'TIMEOUT_ERROR', 'Request timed out.'
    
    return 'ERROR', 'Unknown error after all retries.'


progress_lock = threading.Lock()
provider_progress: Dict[str, Dict[str, int]] = {}


def update_progress(con: sqlite3.Connection, provider: str, status: str, key: str):
    with progress_lock:
        if status == 'VALID' or status == 'QUOTA_EXCEEDED':
            provider_progress[provider]["valid_count"] += 1
            insert_valid_key(con, provider, key)
        
        provider_progress[provider]["checked"] += 1

        # Clear the line before printing progress
        print(f"\r{' ' * 80}\r", end='', flush=True)

        # Print progress line for this provider
        checked = provider_progress[provider]["checked"]
        total = provider_progress[provider]["total"]
        valid_count = provider_progress[provider]["valid_count"]
        progress_line = f"{provider.upper()}: {checked}/{total} (valid: {valid_count})"
        print(f"\r{progress_line}", end='', flush=True)


async def process_and_validate(tasks_to_run: List[Tuple[str, str]], con: sqlite3.Connection):
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
    
    async def process_with_semaphore(session: aiohttp.ClientSession, key: str, provider: str):
        async with semaphore:
            status, _ = await validate_key(session, provider, key)
            update_progress(con, provider, status, key)

    async with aiohttp.ClientSession() as session:
        tasks = [process_with_semaphore(session, key, provider) for key, provider in tasks_to_run]
        await asyncio.gather(*tasks)


async def main():
    print("Starting parallel database queries for all providers...")
    
    all_keys_by_provider: Dict[str, List[str]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(PROVIDER_CONFIGS)) as db_executor:
        future_to_provider = {
            db_executor.submit(get_candidates_from_db, config["queries"], config["prefixes"]): name
            for name, config in PROVIDER_CONFIGS.items()
        }
        
        for future in concurrent.futures.as_completed(future_to_provider):
            provider = future_to_provider[future]
            try:
                candidates = future.result()
                extracted_keys: Set[str] = set()
                for line in candidates:
                    keys = extract_api_keys(line, PROVIDER_CONFIGS[provider]["patterns"])
                    extracted_keys.update(keys)
                
                all_keys_by_provider[provider] = sorted(list(extracted_keys))
                provider_progress[provider] = {"checked": 0, "total": len(all_keys_by_provider[provider]), "valid_count": 0}
            except Exception as exc:
                print(f"\nDB query for {provider.upper()} failed: {exc}")
    
    all_tasks_for_validation = []
    for provider, keys in all_keys_by_provider.items():
        for key in keys:
            all_tasks_for_validation.append((key, provider))
    
    total_keys = len(all_tasks_for_validation)
    print(f"\nCollected {total_keys} unique keys. Starting async validation...")
    
    con = init_database_valid(VALID_DB_PATH)
    try:
        if all_tasks_for_validation:
            await process_and_validate(all_tasks_for_validation, con)
    finally:
        con.close()

    print() 
    print("\nValidation complete. Results saved to database.")
    
    for provider, data in sorted(provider_progress.items()):
        valid_count = data["valid_count"]
        if data["total"] > 0:
            print(f"{provider.upper()}: Found {valid_count} valid keys out of {data['total']} checked.")
    
    print("All done.")

if __name__ == "__main__":
    asyncio.run(main())
