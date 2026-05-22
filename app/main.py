from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from app.config import ConfigManager
from app.web import create_app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="GitHub LLM Key Searcher")
    parser.add_argument("--config", default="config.yaml", help="path to config yaml")
    parser.add_argument("--db", default="data/app.db", help="sqlite database path")
    parser.add_argument("--host", default="", help="override web host")
    parser.add_argument("--port", type=int, default=0, help="override web port")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    cfg = ConfigManager(args.config).get()
    host = args.host or cfg.web.host
    port = args.port or cfg.web.port
    app = create_app(args.config, args.db)
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
