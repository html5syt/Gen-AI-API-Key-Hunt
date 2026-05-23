# GitHub LLM Key Searcher

A GitHub LLM key discovery and validation service with concurrent search + validation, a session-based Web UI, validated-key API, CSV export, periodic background scanning, per-channel proxy support, custom channels/queries, file-based configuration, and Docker/GHCR deployment.

## Features

- **Concurrent search and validation**: discovered key candidates are queued and validated immediately, then periodically rechecked.
- **Authenticated Web UI** (custom host/port):
  - session login only, no basic auth
  - found keys view with expandable validation details
  - validated keys view with expandable validation details
  - validation logs view for all non-pending outcomes
  - dashboard with runtime and database stats
- **API for validated keys** with token auth.
- **YAML config replaces env vars**, and config can be edited from the GUI.
- **Resident scheduler** with configurable scan interval, defaulting to 8 hours.
- **Random validation sweeps** for pending and sampled validated keys.
- **Placeholder key filtering** before insert/validation.
- **Per-channel proxy** configuration.
- **Custom channels** with custom search expressions and regex extraction rules.
- **Docker image** published to GitHub Container Registry.

## Project Structure

```text
app/
  config.py
  database.py
  searcher.py
  validator.py
  pipeline.py
  web.py
  main.py
  templates/
search_keys.py      # compatibility entrypoint
validate_keys.py    # compatibility entrypoint
```

## Quick Start

### 1) Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2) Create config file

```bash
cp config.yaml.example config.yaml
```

Fill at least:

- `github.tokens`
- `web.username`
- `web.password_hash` (SHA-256 hex of your password)
- `web.session_secret`
- `api.token` (SHA-256 hex of your API token)

> The default generated config stores SHA-256 hashes only. You can paste a raw password or token into the UI and it will be hashed before saving.

### 3) Start service

```bash
python -m app.main --config config.yaml --db data/app.db
```

Open: `http://127.0.0.1:8080` (or your configured host/port).

The Web UI uses session login only. Log in with the username and password from `config.yaml`; the UI hashes any raw password or API token you enter before saving it.

## WebUI Routes

- `/login`
- `/`
- `/keys/found`
- `/keys/validated`
- `/validation/logs`
- `/export/validated.csv`
- `/config`

The Web UI supports English and Chinese switching from the top-right language toggle.

## API

Use request header: `X-API-Token: <api.token>`

- `GET /api/v1/validated-keys?limit=100&offset=0&provider=`
- `GET /api/v1/stats`

Example:

```bash
curl -H "X-API-Token: your-token" \
  "http://127.0.0.1:8080/api/v1/validated-keys?limit=20&offset=0"
```

The API is enabled by default. If you disable it in the configuration, requests return 403.

## Docker

### Build locally

```bash
docker build -t github-llm-key-searcher:latest .
```

### Run

```bash
docker run --rm -p 8080:8080 \
  -v $(pwd)/config.yaml:/app/config.yaml \
  -v $(pwd)/data:/app/data \
  github-llm-key-searcher:latest
```

If container access is needed from host network mapping, set `web.host` to `0.0.0.0` in `config.yaml`.

### Run with Compose

`docker-compose.yml` pulls the prebuilt image from GitHub Container Registry instead of building locally:

```bash
docker compose up -d
```

Set `GHCR_IMAGE` to the published image you want to run, for example `ghcr.io/<owner>/<repo>:latest`.

### Published Image

The CI workflow publishes images to GitHub Container Registry under `ghcr.io/<owner>/<repo>`.
Use `latest` from the default branch or the SHA-tagged image from each CI run.

## Security Notes

- Use only for authorized security research and leak triage.
- Passwords and API tokens are stored as SHA-256 hex hashes by default.
- Set a strong API token and session secret.
- Review custom channel expressions carefully.

## License

MIT
