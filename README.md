# Gen-AI-API-Key-Hunt

A small utility that searches public GitHub repositories for potential Gen AI API key leaks. It crafts focused queries for popular providers, walks paginated results, and stores concise metadata in a SQLite database. The script uses adaptive search to bypass GitHub's 1000-result limit by recursively expanding queries when needed. This project is intended for security researchers and developers who need to triage potential secrets exposure in public code.

## Disclaimer and Compliance

This tool is intended for educational and security research purposes only. It is designed to help security professionals and developers identify potential secret leaks in public repositories they are authorized to analyze.

Users are solely responsible for ensuring their use of this tool complies with all applicable laws and terms of service, including the [GitHub Acceptable Use Policies](https://docs.github.com/en/site-policy/acceptable-use-policies/github-acceptable-use-policies). The author assumes no liability for any misuse or damage caused by this project.

The script is designed to operate within GitHub's policies by adhering to the following principles:

- **Purpose of Use**: The script is intended for security research, a permissible use of public, non-personal information under **Section 7** of GitHub's policies.
- **API Usage**: It exclusively uses the official GitHub REST API for data collection, which is the approved method for automated access.
- **Rate Limiting**: It honors API rate limits to avoid placing an undue burden on GitHub's infrastructure, in line with **Section 4**.
- **Authorized Access**: The tool only accesses publicly available data and does not attempt to gain unauthorized access to private information, complying with **Section 5**.

This script does not store, validate, or use the discovered keys; it only identifies their location. It is the user's responsibility to handle any discovered information ethically and legally.

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

## Optional Configuration

You can fine-tune the script's behavior with these optional environment variables:

- **`REQUEST_TIMEOUT_SECONDS`**: Timeout for API requests in seconds. Default: `10`.
- **`PAGE_DELAY_SECONDS`**: Delay between paginated search requests. Default: `2`.
- **`MAX_PAGES`**: Maximum number of pages to fetch for a single query branch. Default: `20`.
- **`DEFAULT_BACKOFF_SECONDS`**: Initial delay in seconds when a token is rate-limited without a `Retry-After` header. Default: `60`.
- **`MAX_BACKOFF_SECONDS`**: Maximum backoff delay for exponential backoff. Default: `600`.
- **`GITHUB_USER_AGENT`**: Custom User-Agent string for API requests. Default: `api-key-hunt/1.0`.

## FAQ

### How does token rotation work?

The script selects tokens in a round‑robin order and reads `X‑RateLimit‑Remaining`/`X‑RateLimit‑Reset`. Exhausted tokens are cooled down until reset. If all tokens are limited, the script waits and resumes automatically.

### How does the adaptive search work?

GitHub's Search API caps results at 1000 per query. To find more potential leaks, the script first probes the total count for a base query (e.g., `OPENAI_API_KEY=sk-`). If the count is 1000 or more, it recursively expands the search by appending one character at a time (e.g., `sk-a`, `sk-b`, etc.) until each sub-query returns fewer than 1000 results. This partitions the search space to uncover a more comprehensive set of results.

### What providers are covered?

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

Run directly as a script to generate the DB results file:

```bash
python3 ./search_keys.py
```

Or import the function in Python to run a single query programmatically:

```python
from search_keys import adaptive_search, init_database

# Initialize a database connection
con = init_database("my_results.db")

# Run a single adaptive search
results_count = adaptive_search(con, "OPENAI_API_KEY=sk-")
print(f"Found {results_count} new items")

# Close the connection when done
con.close()
```

## License

[MIT](./LICENSE)
