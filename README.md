# API-Key-Hunt

A small utility that searches public GitHub repositories for potential API key leaks. It crafts focused queries for popular providers, walks paginated results, fetches raw files, and stores concise metadata in a JSON file. This project is intended for security researchers and developers who need to triage potential secrets exposure in public code.

## Deployment

This is a Python script, no special deployment is required. To run locally from the repository root:

```bash
python3 ./search_keys.py
```

On Windows PowerShell:

```powershell
python .\search_keys.py
```

## Environment Variables

To run this project, configure GitHub tokens using environment variables or a `.env` file.

Required (choose one approach):

- `GITHUB_TOKENS` — comma‑separated list of tokens for rotation (e.g. `ghp_xxx1,ghp_xxx2`)
- `GITHUB_TOKEN` — a single token (used if `GITHUB_TOKENS` is not set)

Optional: install `python-dotenv` and place a `.env` in the repository root (see `.env.example`):

```text
GITHUB_TOKENS=ghp_xxx1,ghp_xxx2
# or
# GITHUB_TOKEN=ghp_xxx
```

The script rotates multiple tokens round‑robin and honors GitHub rate limits. With one token, it behaves the same without rotation.

## FAQ

#### How does token rotation work?

The script selects tokens in a round‑robin order and reads `X‑RateLimit‑Remaining`/`X‑RateLimit‑Reset`. Exhausted tokens are cooled down until reset. If all tokens are limited, the script waits and resumes automatically.

#### What providers are covered?

Common ones like OpenAI, Anthropic, Google/Gemini, OpenRouter, Mistral, DeepSeek, Grok/Groq, and xAI. It combines typical environment variable names with known key prefixes and expands the first character after prefixes to avoid the 1000‑result window.

## Installation

Use a recent Python (3.10+). Optionally create a virtual environment. Install dependencies (for example, `requests`; `python-dotenv` is optional).

```bash
python -m venv .venv
source .venv/bin/activate  # PowerShell: .venv\Scripts\Activate.ps1
pip install -U requests python-dotenv
```

## Run Locally

Clone the project and change directory:

```bash
git clone https://github.com/Aletheia-Praxis/api-key-hunt
cd api-key-hunt
```

Set environment variables (examples) and run the script:

```bash
export GITHUB_TOKENS="ghp_xxx1,ghp_xxx2"   # PowerShell: $env:GITHUB_TOKENS = "ghp_xxx1,ghp_xxx2"
python3 ./search_keys.py
```

## Usage/Examples

Run directly as a script to generate the JSON results file:

```bash
python3 ./search_keys.py
```

Or import the function in Python to run a single query programmatically:

```python
from search_keys import github_search

results = github_search("OPENAI_API_KEY=sk-")
print(len(results), "items")
```

## License

[MIT](./LICENSE)
