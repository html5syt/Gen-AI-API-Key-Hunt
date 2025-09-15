# api-key-hunt

api-key-hunt searches public GitHub repositories for potential API key leaks. It builds focused search queries for common providers, walks paginated results, fetches raw files, and saves compact metadata to a JSON file. The tool supports one or multiple GitHub tokens and rotates them while respecting rate limits.

The script understands typical environment variable names and well‑known key prefixes (for example OpenAI, Anthropic, Google/Gemini, OpenRouter, Mistral, DeepSeek, Grok/Groq, xAI). To reduce the chance of hitting the 1000‑result window in GitHub Search, it expands the first character after known prefixes. Results are checkpointed after every query so you do not lose progress.

You need Python 3.10+ and internet access. Provide a GitHub personal access token with read access to public repositories. If you prefer configuration in a file, install `python-dotenv` so the script can read variables from a `.env` in the repository root.

Clone the repository and, if you like, create a virtual environment. Install the needed packages (for example `requests`; `python-dotenv` is optional). No special build steps are required.

Configure authentication using environment variables. If you set `GITHUB_TOKENS`, provide a comma‑separated list; the script will use exactly as many tokens as you specify and will rotate them automatically. If you set only `GITHUB_TOKEN`, the script uses that single token. On Windows PowerShell you can run:

```powershell
$env:GITHUB_TOKENS = "ghp_xxx1,ghp_xxx2"
# or
$env:GITHUB_TOKEN = "ghp_xxx"
```

If you prefer a file, create `.env` in the repository root and add either a list in `GITHUB_TOKENS` or a single `GITHUB_TOKEN`. When `python-dotenv` is installed, the script loads this file on startup.

Run the tool from the repository root. On Windows PowerShell:

```powershell
python .\search_keys.py
```

On macOS or Linux:

```bash
python3 ./search_keys.py
```

By default, output is written to `github_api_key_search_results.json`. Each entry includes the query used, repository name, file path, GitHub URL, and the first matched line if available. The format is easy to scan manually and simple to parse with other tools.

Rate limits are handled automatically. The script reads `X‑RateLimit‑Remaining` and `X‑RateLimit‑Reset`. An exhausted token is cooled down until reset; with multiple tokens, the script switches to the next one. If all tokens are limited, it waits until the earliest reset and resumes. With a single token, the same logic applies without rotation.

Please ensure your usage complies with GitHub’s Terms of Service. Search results can be incomplete due to API windows, repository changes, or tricky file formats. Matching is heuristic and intended for triage rather than definitive classification. If you encounter 403 errors, you likely hit a rate limit; add tokens or wait until reset. If your `.env` is not applied, install `python-dotenv` or export variables in your shell instead.

MIT License. See `LICENSE` for details.
