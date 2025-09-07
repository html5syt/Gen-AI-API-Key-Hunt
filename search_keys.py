import requests
import time
import urllib.parse
import json

GITHUB_TOKEN = "ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
headers = {"Authorization": f"token {GITHUB_TOKEN}"}

queries = [
    # OpenAI
    'OPENAI_API_KEY=sk-',
    'OPENAI_API_KEY=sk-proj-',

    # Anthropic
    'ANTHROPIC_API_KEY=sk-ant-',
    'ANTHROPIC_API_KEY=sk-ant-api03-',
    'ANTHROPIC_API_KEY=apikey_',

    # Google / Gemini
    'GOOGLE_API_KEY=AIza',
    'GEMINI_API_KEY=AIza',

    # OpenRouter
    'OPENROUTER_API_KEY=sk-',
    'OPENROUTER_API_KEY=sk-or-v1-',
    'OPEN_ROUTER_API_KEY=sk-',
    'OPEN_ROUTER_API_KEY=sk-or-v1-',

    # Qwen
    'QWEN_API_KEY=',

    # Azure
    'AZURE_OPENAI_KEY=',
    'AZURE_OPENAI_ENDPOINT=',

    # Mistral
    'MISTRAL_API_KEY=',

    # DeepSeek
    'DEEPSEEK_API_KEY=',
    'DEEPSEEK_API_KEY=sk-',

    # Groq
    'GROK_API_KEY=',
    'GROQ_API_KEY=',
    'GROK_API_KEY=gsk_',
    'GROQ_API_KEY=gsk_',

    # XAI
    'XAI_API_KEY='
]

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
