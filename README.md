# GitHub LLM Key Searcher

A complete GitHub LLM Key Searcher with concurrent search + validation, authenticated WebUI, validated-key API, CSV export, periodic background scanning, per-channel proxy, custom channels/queries, file-based configuration, and Docker support.

## Features

- **Concurrent search and validation**: discovered key candidates are queued and validated immediately.
- **Authenticated WebUI** (custom host/port):
  - login authentication
  - found keys view
  - validated keys view
  - validated keys CSV export
  - dashboard with runtime/data stats
- **API for validated keys** with token auth.
- **YAML config replaces env vars**, and config can be edited from GUI.
- **Resident scheduler** with configurable scan interval.
- **Per-channel proxy** configuration.
- **Custom channels** with custom search expressions and regex extraction rules.
- **Docker image** for container deployment.

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
- `web.password_hash`
- `web.session_secret`
- `api.token`

> The default generated config uses `admin` as the initial password. Change it immediately in GUI or by replacing `web.password_hash`.

### 3) Start service

```bash
python -m app.main --config config.yaml --db data/app.db
```

Open: `http://127.0.0.1:8080` (or your configured host/port).

## WebUI Routes

- `/login`
- `/`
- `/keys/found`
- `/keys/validated`
- `/export/validated.csv`
- `/config`

## API

Use request header: `X-API-Token: <api.token>`

- `GET /api/v1/validated-keys?limit=100&offset=0&provider=`
- `GET /api/v1/stats`

## Docker

### Build

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

## Security Notes

- Use only for authorized security research and leak triage.
- Passwords are stored as PBKDF2-SHA256 hashes.
- Set a strong API token and session secret.
- Review custom channel expressions carefully.

## License

MIT
