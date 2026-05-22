from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import tempfile
from typing import Any, Callable

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.config import AppConfig, ChannelConfig, ConfigManager, hash_password, verify_password
from app.database import Database
from app.pipeline import ScanPipeline


def _read_form_field(form_data: Any, key: str, default: str = "") -> str:
    value = form_data.get(key)
    if value is None:
        return default
    return str(value)


def _require_login(request: Request) -> None:
    if request.session.get("logged_in") is True:
        return
    raise HTTPException(status_code=401, detail="unauthorized")


def create_app(config_path: str, db_path: str) -> FastAPI:
    config_manager = ConfigManager(config_path)
    database = Database(db_path)
    pipeline = ScanPipeline(config_manager, database)

    app = FastAPI(title="GitHub LLM Key Searcher")
    app.add_middleware(SessionMiddleware, secret_key=config_manager.get().web.session_secret)
    templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

    @app.on_event("startup")
    def _startup() -> None:
        pipeline.start()

    @app.on_event("shutdown")
    def _shutdown() -> None:
        pipeline.stop()

    def require_login_dependency(request: Request) -> None:
        _require_login(request)

    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request=request, name="login.html", context={"error": ""})

    @app.post("/login")
    async def login_submit(request: Request) -> RedirectResponse | HTMLResponse:
        form_data = await request.form()
        username = _read_form_field(form_data, "username")
        password = _read_form_field(form_data, "password")
        cfg = config_manager.get()
        if username == cfg.web.username and verify_password(password, cfg.web.password_hash):
            request.session["logged_in"] = True
            return RedirectResponse(url="/", status_code=302)

        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": "用户名或密码错误"},
            status_code=401,
        )

    @app.get("/logout")
    async def logout(request: Request) -> RedirectResponse:
        request.session.clear()
        return RedirectResponse(url="/login", status_code=302)

    @app.get("/", response_class=HTMLResponse, dependencies=[Depends(require_login_dependency)])
    async def dashboard(request: Request) -> HTMLResponse:
        db_stats = database.get_stats()
        runtime = pipeline.runtime_stats()
        return templates.TemplateResponse(
            request=request,
            name="dashboard.html",
            context={"db_stats": db_stats, "runtime": runtime},
        )

    @app.get("/keys/found", response_class=HTMLResponse, dependencies=[Depends(require_login_dependency)])
    async def found_keys(request: Request, page: int = 1, status: str = "") -> HTMLResponse:
        cfg = config_manager.get()
        page_size = max(1, cfg.web.page_size)
        offset = max(0, page - 1) * page_size
        effective_status = status.strip() or None
        rows = database.list_found(limit=page_size, offset=offset, status=effective_status)
        return templates.TemplateResponse(
            request=request,
            name="found_keys.html",
            context={"rows": rows, "page": page, "status": status},
        )

    @app.get("/keys/validated", response_class=HTMLResponse, dependencies=[Depends(require_login_dependency)])
    async def validated_keys(request: Request, page: int = 1, provider: str = "") -> HTMLResponse:
        cfg = config_manager.get()
        page_size = max(1, cfg.web.page_size)
        offset = max(0, page - 1) * page_size
        provider_value = provider.strip() or None
        rows = database.list_validated(limit=page_size, offset=offset, provider=provider_value)
        return templates.TemplateResponse(
            request=request,
            name="validated_keys.html",
            context={"rows": rows, "page": page, "provider": provider},
        )

    @app.get("/export/validated.csv", dependencies=[Depends(require_login_dependency)])
    async def export_validated() -> FileResponse:
        with tempfile.NamedTemporaryFile(prefix="validated-", suffix=".csv", delete=False) as tmp:
            tmp_path = tmp.name
        database.export_validated_csv(tmp_path)
        return FileResponse(path=tmp_path, filename="validated_keys.csv", media_type="text/csv")

    @app.get("/config", response_class=HTMLResponse, dependencies=[Depends(require_login_dependency)])
    async def config_page(request: Request) -> HTMLResponse:
        cfg = config_manager.get()
        channels_json = json.dumps([asdict(c) for c in cfg.channels], indent=2, ensure_ascii=False)
        return templates.TemplateResponse(
            request=request,
            name="config.html",
            context={"cfg": cfg, "channels_json": channels_json, "message": ""},
        )

    @app.post("/config", response_class=HTMLResponse, dependencies=[Depends(require_login_dependency)])
    async def config_submit(request: Request) -> HTMLResponse:
        form_data = await request.form()
        cfg = config_manager.get()

        cfg.github.tokens = [token.strip() for token in _read_form_field(form_data, "github_tokens").split(",") if token.strip()]
        cfg.github.user_agent = _read_form_field(form_data, "github_user_agent", cfg.github.user_agent)
        cfg.github.request_timeout_seconds = int(_read_form_field(form_data, "github_timeout", str(cfg.github.request_timeout_seconds)))
        cfg.github.max_pages = int(_read_form_field(form_data, "github_max_pages", str(cfg.github.max_pages)))
        cfg.github.page_delay_seconds = float(_read_form_field(form_data, "github_page_delay", str(cfg.github.page_delay_seconds)))

        cfg.scanner.interval_seconds = int(_read_form_field(form_data, "scanner_interval", str(cfg.scanner.interval_seconds)))
        cfg.scanner.search_workers = int(_read_form_field(form_data, "search_workers", str(cfg.scanner.search_workers)))
        cfg.scanner.validate_workers = int(_read_form_field(form_data, "validate_workers", str(cfg.scanner.validate_workers)))

        cfg.validation.request_timeout_seconds = int(_read_form_field(form_data, "validation_timeout", str(cfg.validation.request_timeout_seconds)))
        cfg.validation.retries = int(_read_form_field(form_data, "validation_retries", str(cfg.validation.retries)))
        cfg.validation.initial_backoff_seconds = int(_read_form_field(form_data, "validation_backoff", str(cfg.validation.initial_backoff_seconds)))

        cfg.web.host = _read_form_field(form_data, "web_host", cfg.web.host)
        cfg.web.port = int(_read_form_field(form_data, "web_port", str(cfg.web.port)))
        cfg.web.username = _read_form_field(form_data, "web_username", cfg.web.username)
        cfg.web.session_secret = _read_form_field(form_data, "web_session_secret", cfg.web.session_secret)
        cfg.web.page_size = int(_read_form_field(form_data, "web_page_size", str(cfg.web.page_size)))
        new_password = _read_form_field(form_data, "web_password")
        if new_password.strip():
            cfg.web.password_hash = hash_password(new_password.strip())

        cfg.api.enabled = _read_form_field(form_data, "api_enabled", "off") == "on"
        cfg.api.token = _read_form_field(form_data, "api_token", cfg.api.token)

        channels_text = _read_form_field(form_data, "channels_json", "[]")
        channels_loaded = json.loads(channels_text)
        channels: list[ChannelConfig] = []
        if isinstance(channels_loaded, list):
            for item in channels_loaded:
                if not isinstance(item, dict):
                    continue
                channels.append(
                    ChannelConfig(
                        name=str(item.get("name", "")).strip(),
                        provider=str(item.get("provider", "")).strip().lower(),
                        query=str(item.get("query", "")).strip(),
                        extract_patterns=[str(x) for x in item.get("extract_patterns", []) if str(x).strip()],
                        proxy=str(item.get("proxy", "")),
                        enabled=bool(item.get("enabled", True)),
                    )
                )
        cfg.channels = [c for c in channels if c.name and c.provider and c.query and c.extract_patterns]

        config_manager.update(cfg)
        channels_json = json.dumps([asdict(c) for c in cfg.channels], indent=2, ensure_ascii=False)
        return templates.TemplateResponse(
            request=request,
            name="config.html",
            context={"cfg": cfg, "channels_json": channels_json, "message": "配置已保存（端口变更需重启生效）"},
        )

    @app.post("/scan/run-now", dependencies=[Depends(require_login_dependency)])
    async def run_now() -> RedirectResponse:
        pipeline.trigger_scan_now()
        return RedirectResponse(url="/", status_code=302)

    def _api_auth(token_provider: Callable[[], AppConfig], request: Request) -> None:
        cfg = token_provider()
        if not cfg.api.enabled:
            raise HTTPException(status_code=403, detail="api is disabled")
        token = request.headers.get("X-API-Token", "")
        if token != cfg.api.token:
            raise HTTPException(status_code=401, detail="invalid api token")

    @app.get("/api/v1/validated-keys")
    async def api_validated_keys(request: Request, limit: int = 100, offset: int = 0, provider: str = "") -> JSONResponse:
        _api_auth(config_manager.get, request)
        rows = database.list_validated(limit=max(1, min(limit, 1000)), offset=max(0, offset), provider=provider or None)
        return JSONResponse({"items": rows, "limit": limit, "offset": offset})

    @app.get("/api/v1/stats")
    async def api_stats(request: Request) -> JSONResponse:
        _api_auth(config_manager.get, request)
        return JSONResponse({"database": database.get_stats(), "runtime": pipeline.runtime_stats()})

    return app
