import requests
import time
import urllib.parse

GITHUB_TOKEN = "ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"

headers = {"Authorization": f"token {GITHUB_TOKEN}"}

queries = [
    'OPENAI_API_KEY=sk-',
    'ANTHROPIC_API_KEY=sk-',
    'ANTHROPIC_API_KEY=an-',
    'GOOGLE_API_KEY=AIza',
    'GEMINI_API_KEY=AIza',
    'OPENROUTER_API_KEY=sk-',
    'OPENROUTER_API_KEY=or_',
    'OPEN_ROUTER_API_KEY=sk-',
    'QWEN_API_KEY=QWEN-',
    'AZURE_OPENAI_KEY=',
    'AZURE_OPENAI_ENDPOINT=',
    'MISTRAL_API_KEY=',
    'DEEPSEEK_API_KEY=',
    'GROK_API_KEY=',
    'GROQ_API_KEY=',
    'XAI_API_KEY='
]

def github_search(query, per_page=100):
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

        results.extend(items)

        if len(items) < per_page or page >= 10:
            break

        page += 1
        time.sleep(2)

    return results


if __name__ == "__main__":
    all_results = {}

    for q in queries:
        print(f"Searching for: {q}")
        res = github_search(q)
        all_results[q] = res
        print(f"  -> Found {len(res)} items")

    import json
    with open("github_api_key_search_results.json", "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)

    print("Done. Results saved to github_api_key_search_results.json")
