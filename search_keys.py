import requests
import time
import urllib.parse
import json
from typing import Dict, Iterable, List

GITHUB_TOKEN = "ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
headers = {"Authorization": f"token {GITHUB_TOKEN}"}

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
    google_prefixes: List[str] = ["AIza"]
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

def github_search(query, per_page=50):
    url = f"https://api.github.com/search/code?q={urllib.parse.quote(query)}&per_page={per_page}"
    results = []
    page = 1

    while True:
        paged_url = f"{url}&page={page}"
        r = requests.get(paged_url, headers=headers)
        if r.status_code != 200:
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

            raw_url = file_url.replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
            try:
                raw_resp = requests.get(raw_url, headers=headers, timeout=10)
                if raw_resp.status_code == 200:
                    content = raw_resp.text
                    matched_line = None
                    for line in content.splitlines():
                        if query.split("=")[0] in line:
                            matched_line = line.strip()
                            break
                else:
                    matched_line = None
            except Exception:
                matched_line = None

            results.append({
                "search_query": query,
                "repository": repo_name,
                "file_path": file_path,
                "file_url": file_url,
                "matched_line": matched_line
            })

        if len(items) < per_page or page >= 20:
            break

        page += 1
        time.sleep(2)

    return results


if __name__ == "__main__":
    all_results = []

    for q in queries:
        print(f"Searching for: {q}")
        res = github_search(q)
        all_results.extend(res)
        print(f"  -> Found {len(res)} items")

    with open("github_api_key_search_results.json", "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)

    print("Done. Results saved to github_api_key_search_results.json")
