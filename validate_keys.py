import sqlite3
import requests
import re
from typing import List, Optional, Set

DB_PATH = "4_api_keys.db"
VALID_KEYS_FILE = "valid_gemini_keys.txt"

def get_gemini_candidates_from_db() -> List[str]:
    """
    Retrieves potential Gemini API key candidates from the database.

    Fetches all 'matched_line' entries where the search query is related to Google or Gemini.

    Returns:
        A list of strings, where each string is a line containing a potential key.
    """
    candidates = []
    try:
        with sqlite3.connect(DB_PATH) as con:
            cur = con.cursor()
            # Select lines from searches for Google/Gemini keys
            cur.execute("""
                SELECT matched_line FROM results
                WHERE search_query LIKE '%GOOGLE_API_KEY%'
                   OR search_query LIKE '%GEMINI_API_KEY%'
                   OR search_query LIKE '%GEMINI_KEY%';
            """)
            rows = cur.fetchall()
            candidates = [row[0] for row in rows if row[0]]
    except sqlite3.OperationalError as e:
        print(f"Error connecting to or reading from database: {e}")
        print(f"Please ensure the database '{DB_PATH}' exists and is not corrupted.")
    return candidates

def extract_api_key(line: str) -> Optional[str]:
    """
    Extracts a Gemini API key from a line of text using a regex.

    Looks for the 'AIzaSy' prefix followed by a sequence of valid key characters.

    Args:
        line: The string to search for a key.

    Returns:
        The extracted API key as a string, or None if no key is found.
    """
    # Gemini API keys start with "AIzaSy" and contain alphanumeric chars, underscores, and hyphens.
    match = re.search(r'(AIzaSy[A-Za-z0-9\-_]+)', line)
    if match:
        return match.group(1)
    return None

def is_gemini_key_valid(api_key: str) -> bool:
    """
    Validates a Gemini API key by making a simple request to the Google AI API.

    Args:
        api_key: The Gemini API key to validate.

    Returns:
        True if the key is valid, False otherwise.
    """
    # This endpoint lists available models, a lightweight way to check key validity.
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    try:
        response = requests.get(url, timeout=10)
        # A 200 OK response means the key is valid.
        # A 400/403 error indicates an invalid or disabled key.
        if response.status_code == 200:
            print(f"  [+] VALID: {api_key[:10]}...")
            return True
        else:
            # This key is likely invalid, expired, or has incorrect permissions.
            # print(f"  [-] INVALID: {api_key[:10]}... (Status: {response.status_code})")
            return False
    except requests.RequestException as e:
        # Network error or timeout
        # print(f"  [!] ERROR validating {api_key[:10]}...: {e}")
        return False

def main():
    """
    Main function to orchestrate the key validation process.
    """
    print("Starting Gemini API key validation process...")
    
    candidates = get_gemini_candidates_from_db()
    if not candidates:
        print("No potential Gemini keys found in the database.")
        return

    print(f"Found {len(candidates)} potential lines containing keys. Extracting and validating...")
    
    extracted_keys: Set[str] = set()
    for line in candidates:
        key = extract_api_key(line)
        if key:
            extracted_keys.add(key)

    if not extracted_keys:
        print("Could not extract any keys from the database candidates.")
        return
        
    print(f"Extracted {len(extracted_keys)} unique keys. Now checking their validity...")

    valid_keys = []
    for key in sorted(list(extracted_keys)):
        if is_gemini_key_valid(key):
            valid_keys.append(key)

    if valid_keys:
        print(f"\nFound {len(valid_keys)} valid Gemini API keys.")
        with open(VALID_KEYS_FILE, 'w') as f:
            for key in valid_keys:
                f.write(key + '\n')
        print(f"Valid keys have been saved to '{VALID_KEYS_FILE}'.")
    else:
        print("\nNo valid Gemini API keys were found.")

if __name__ == "__main__":
    main()
