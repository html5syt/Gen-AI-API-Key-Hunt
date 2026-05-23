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
from starlette.responses import Response

from app.config import (
    AppConfig,
    ChannelConfig,
    ConfigManager,
    normalize_secret_hash,
    ValidationApiProfile,
    verify_password,
    verify_secret,
)
from app.database import Database
from app.pipeline import ScanPipeline


_TRANSLATIONS: dict[str, dict[str, str]] = {
    "en": {
        "app_name": "GitHub LLM Key Searcher",
        "app_tagline": "Scan, validate, recheck, and clean up keys with a configurable workflow.",
        "nav_dashboard": "Dashboard",
        "nav_found_keys": "Found Keys",
        "nav_validated_keys": "Validated Keys",
        "nav_validation_logs": "Validation Logs",
        "nav_configuration": "Configuration",
        "nav_export_csv": "Export CSV",
        "nav_logout": "Logout",
        "nav_language": "Language",
        "login_title": "Sign in",
        "login_prompt": "Use the username and password configured in the WebUI settings.",
        "login_username": "Username",
        "login_password": "Password",  # nosec B105
        "login_button": "Login",
        "login_hint": "Passwords are stored as SHA-256 hashes after saving.",
        "login_invalid": "Invalid username or password.",
        "dashboard_title": "Control Center",
        "dashboard_subtitle": "Trigger a scan now or let the scheduler continue in the background.",
        "dashboard_found_total": "Total discovered keys",
        "dashboard_validated_total": "Keys still considered usable",
        "dashboard_queue_size": "Validation jobs waiting",
        "dashboard_log_count": "Validation log entries",
        "dashboard_run_now": "Run Scan Now",
        "dashboard_found_by_provider": "Found by Provider",
        "dashboard_validation_breakdown": "Validation Status Breakdown",
        "found_title": "Found Keys",
        "found_desc": "Keys that look like real secrets are kept, obvious placeholders are filtered out before they reach this view.",
        "filter_status": "Filter by status",
        "filter_button": "Filter",
        "col_id": "ID",
        "col_channel": "Channel",
        "col_provider": "Provider",
        "col_api_key": "API Key",
        "col_repo": "Repo",
        "col_path": "Path",
        "col_status": "Status",
        "col_detail": "Detail",
        "col_count": "Count",
        "next_page": "Next page",
        "validated_title": "Validated Keys",
        "validated_desc": "Keys that passed validation and are still tracked by the database.",
        "filter_provider": "Filter by provider",
        "col_last_validated": "Last Validated",
        "logs_title": "Validation Logs",
        "logs_desc": "Every validation attempt is stored here, including failures and deletions.",
        "col_time": "Time",
        "col_source": "Source",
        "col_mode": "Mode",
        "config_title": "Configuration",
        "config_desc": "Edit channels and validation profiles with the GUI tables below. Advanced JSON remains available if you need it.",
        "section_github": "GitHub",
        "section_scanner": "Scanner",
        "section_validation": "Validation",
        "section_web": "Web",
        "section_api": "API",
        "section_profiles": "Validation Profiles",
        "section_channels": "Channels",
        "section_advanced": "Advanced JSON",
        "config_save": "Save configuration",
        "config_saved": "Configuration saved. Restart required for host or port changes.",
        "config_tokens": "Tokens (comma separated)",
        "config_user_agent": "User-Agent",
        "config_timeout": "Request timeout seconds",
        "config_max_pages": "Max pages",
        "config_page_delay": "Page delay seconds",
        "config_scan_interval": "Scan interval seconds",
        "config_search_workers": "Search workers",
        "config_validate_workers": "Validation workers",
        "config_validation_timeout": "Validation timeout seconds",
        "config_retry_count": "Retry count",
        "config_backoff": "Initial backoff seconds",
        "config_revalidation_interval": "Revalidation interval seconds",
        "config_pending_batch": "Pending batch size",
        "config_validated_sample": "Validated sample size",
        "config_ping_prompt": "Ping prompt",
        "config_delete_invalid": "Remove invalid keys from the database",
        "config_host": "Host",
        "config_port": "Port",
        "config_username": "Username",
        "config_password": "New password",  # nosec B105
        "config_session_secret": "Session secret",  # nosec B105
        "config_page_size": "Page size",
        "config_enable_api": "Enable API",
        "config_api_token": "New API token",  # nosec B105
        "config_secret_hint": "Credentials are stored as SHA-256 hashes after saving.",
        "config_profiles_hint": "Each profile maps to a compatible API format and declares the request details.",
        "config_channels_hint": "Each channel links to a validation profile by name.",
        "config_json_hint": "Use JSON only if you prefer manual editing. GUI values take precedence.",
        "config_json_profiles": "Use JSON for validation profiles",
        "config_json_channels": "Use JSON for channels",
        "config_name": "Name",
        "config_format": "Format",
        "config_base_url": "Base URL",
        "config_path": "Path",
        "config_method": "Method",
        "config_headers": "Headers (JSON)",
        "config_models": "Models",
        "config_key_transport": "Key transport",
        "config_header": "Header",
        "config_prefix": "Prefix",
        "config_query_param": "Query param",
        "config_enabled": "Enabled",
        "config_provider": "Provider",
        "config_query": "Query",
        "config_extract_patterns": "Extract patterns",
        "config_validation_profile": "Validation profile",
        "config_proxy": "Proxy",
        "config_validation_profiles_json": "Validation Profiles JSON",
        "config_channels_json": "Channels JSON",
        "config_new_profile": "new profile",
        "config_new_channel": "new channel",
        "login_language_zh": "中文",
        "login_language_en": "English",
        "status_pending": "Pending",
        "status_valid": "Valid",
        "status_invalid": "Invalid",
        "status_quota_exceeded": "Quota exceeded",
        "status_error": "Error",
        "lang_name_en": "English",
        "lang_name_zh": "中文",
        "switch_to_zh": "中文",
        "switch_to_en": "English",
    },
    "zh": {
        "app_name": "GitHub LLM Key 搜索器",
        "app_tagline": "用可配置的工作流执行搜索、验证、复核和清理。",
        "nav_dashboard": "仪表盘",
        "nav_found_keys": "发现的 Key",
        "nav_validated_keys": "已验证 Key",
        "nav_validation_logs": "验证日志",
        "nav_configuration": "配置",
        "nav_export_csv": "导出 CSV",
        "nav_logout": "退出登录",
        "nav_language": "语言",
        "login_title": "登录",
        "login_prompt": "使用 WebUI 配置里设置的用户名和密码登录。",
        "login_username": "用户名",
        "login_password": "登录口令",  # nosec B105
        "login_button": "登录",
        "login_hint": "密码保存后会以 SHA-256 哈希形式存储。",
        "login_invalid": "用户名或密码不正确。",
        "dashboard_title": "控制中心",
        "dashboard_subtitle": "现在就触发一次扫描，或者让调度器在后台继续运行。",
        "dashboard_found_total": "已发现的 Key 总数",
        "dashboard_validated_total": "仍被视为可用的 Key",
        "dashboard_queue_size": "等待处理的验证任务",
        "dashboard_log_count": "验证日志条数",
        "dashboard_run_now": "立即执行扫描",
        "dashboard_found_by_provider": "按提供商统计发现量",
        "dashboard_validation_breakdown": "验证状态分布",
        "found_title": "发现的 Key",
        "found_desc": "看起来像真实密钥的内容会被保留，明显的占位符会在进入这里之前被过滤掉。",
        "filter_status": "按状态过滤",
        "filter_button": "筛选",
        "col_id": "编号",
        "col_channel": "渠道",
        "col_provider": "提供商",
        "col_api_key": "API Key",
        "col_repo": "仓库",
        "col_path": "文件路径",
        "col_status": "状态",
        "col_detail": "详情",
        "col_count": "数量",
        "next_page": "下一页",
        "validated_title": "已验证 Key",
        "validated_desc": "已经通过验证且仍由数据库跟踪的 Key。",
        "filter_provider": "按提供商过滤",
        "col_last_validated": "最近验证时间",
        "logs_title": "验证日志",
        "logs_desc": "每一次验证尝试都会记录在这里，包括失败和删除。",
        "col_time": "时间",
        "col_source": "来源",
        "col_mode": "模式",
        "config_title": "配置",
        "config_desc": "通过下方的 GUI 表格编辑渠道和验证配置。如果你更喜欢手工编辑，仍然可以使用高级 JSON。",
        "section_github": "GitHub",
        "section_scanner": "扫描器",
        "section_validation": "验证",
        "section_web": "Web",
        "section_api": "API",
        "section_profiles": "验证配置",
        "section_channels": "渠道",
        "section_advanced": "高级 JSON",
        "config_save": "保存配置",
        "config_saved": "配置已保存。若修改了主机或端口，需要重启服务。",
        "config_tokens": "Token（逗号分隔）",
        "config_user_agent": "User-Agent",
        "config_timeout": "请求超时（秒）",
        "config_max_pages": "最大页数",
        "config_page_delay": "分页间隔（秒）",
        "config_scan_interval": "扫描周期（秒）",
        "config_search_workers": "搜索线程数",
        "config_validate_workers": "验证线程数",
        "config_validation_timeout": "验证超时（秒）",
        "config_retry_count": "重试次数",
        "config_backoff": "初始退避（秒）",
        "config_revalidation_interval": "复核间隔（秒）",
        "config_pending_batch": "待处理批量大小",
        "config_validated_sample": "已验证采样数量",
        "config_ping_prompt": "探测提示词",
        "config_delete_invalid": "将无效 Key 从数据库中移除",
        "config_host": "主机",
        "config_port": "端口",
        "config_username": "用户名",
        "config_password": "登录口令",  # nosec B105
        "config_session_secret": "会话密钥",  # nosec B105
        "config_page_size": "分页大小",
        "config_enable_api": "启用 API",
        "config_api_token": "新的 API 凭证",  # nosec B105
        "config_secret_hint": "凭证保存后会以 SHA-256 哈希形式存储。",
        "config_profiles_hint": "每个配置都对应一种兼容的 API 格式，并声明请求细节。",
        "config_channels_hint": "每个渠道通过名称关联到一个验证配置。",
        "config_json_hint": "只有在你想手工编辑时才使用 JSON，界面表格会优先生效。",
        "config_json_profiles": "使用 JSON 编辑验证配置",
        "config_json_channels": "使用 JSON 编辑渠道",
        "config_name": "名称",
        "config_format": "格式",
        "config_base_url": "基础地址",
        "config_path": "路径",
        "config_method": "方法",
        "config_headers": "请求头（JSON）",
        "config_models": "模型列表",
        "config_key_transport": "Key 传递方式",
        "config_header": "请求头名称",
        "config_prefix": "前缀",
        "config_query_param": "查询参数",
        "config_enabled": "启用",
        "config_provider": "提供商",
        "config_query": "查询语句",
        "config_extract_patterns": "提取规则",
        "config_validation_profile": "验证配置",
        "config_proxy": "代理",
        "config_validation_profiles_json": "验证配置 JSON",
        "config_channels_json": "渠道 JSON",
        "config_new_profile": "新配置",
        "config_new_channel": "新渠道",
        "login_language_zh": "中文",
        "login_language_en": "English",
        "status_pending": "待处理",
        "status_valid": "有效",
        "status_invalid": "无效",
        "status_quota_exceeded": "额度不足",
        "status_error": "错误",
        "lang_name_en": "English",
        "lang_name_zh": "中文",
        "switch_to_zh": "中文",
        "switch_to_en": "English",
    },
}


def _normalize_language(value: str | None) -> str:
    return "en" if value == "en" else "zh"


def _translate(language: str, key: str) -> str:
    language_dict = _TRANSLATIONS.get(language, _TRANSLATIONS["en"])
    if key in language_dict:
        return language_dict[key]
    return _TRANSLATIONS["en"].get(key, key)


def _current_url(request: Request) -> str:
    url = request.url.path
    query = str(request.url.query)
    if query:
        url = f"{url}?{query}"
    return url


def _request_language(request: Request) -> str:
    return _normalize_language(request.session.get("lang"))


def _normalize_sort_order(value: str | None) -> str:
    return "asc" if str(value).lower() == "asc" else "desc"


def _normalize_sort_key(value: str | None, allowed: set[str], default: str) -> str:
    candidate = str(value or default)
    return candidate if candidate in allowed else default


def _toggle_sort_order(current_order: str) -> str:
    return "desc" if _normalize_sort_order(current_order) == "asc" else "asc"


def _page_context(request: Request, **extra: Any) -> dict[str, Any]:
    language = _request_language(request)

    def translate(key: str) -> str:
        return _translate(language, key)

    context: dict[str, Any] = {
        "request": request,
        "lang": language,
        "current_url": _current_url(request),
        "t": translate,
    }
    context.update(extra)
    return context


def _render(
    templates: Jinja2Templates,
    request: Request,
    name: str,
    *,
    status_code: int | None = None,
    **context: Any,
) -> HTMLResponse:
    template_context = _page_context(request, **context)
    if status_code is None:
        return templates.TemplateResponse(
            request=request, name=name, context=template_context
        )
    return templates.TemplateResponse(
        request=request, name=name, context=template_context, status_code=status_code
    )


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

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> Response:
        if (
            exc.status_code == 401
            and not request.url.path.startswith("/api/")
            and request.url.path != "/login"
        ):
            return RedirectResponse(url="/login", status_code=302)
        return JSONResponse(
            {"detail": exc.detail},
            status_code=exc.status_code,
            headers=getattr(exc, "headers", None),
        )

    @app.on_event("startup")
    def _startup() -> None:
        pipeline.start()

    @app.on_event("shutdown")
    def _shutdown() -> None:
        pipeline.stop()

    @app.get("/lang/{language}")
    async def set_language(
        language: str, request: Request, next: str = "/"
    ) -> RedirectResponse:
        request.session["lang"] = _normalize_language(language)
        target = next if next.startswith("/") else "/"
        return RedirectResponse(url=target, status_code=302)

    def require_login_dependency(request: Request) -> None:
        _require_login(request)

    def require_web_auth(
        request: Request,
    ) -> None:
        if request.session.get("logged_in") is True:
            return

        raise HTTPException(
            status_code=401,
            detail="unauthorized",
        )

    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request) -> HTMLResponse:
        return _render(templates, request, "login.html", error="")

    @app.post("/login", response_model=None)
    async def login_submit(request: Request) -> Response:
        form_data = await request.form()
        username = _read_form_field(form_data, "username")
        password = _read_form_field(form_data, "password")
        cfg = config_manager.get()
        if username == cfg.web.username and verify_password(password, cfg.web.password_hash):
            request.session["logged_in"] = True
            return RedirectResponse(url="/", status_code=302)

        return _render(
            templates,
            request,
            "login.html",
            error=_translate(_request_language(request), "login_invalid"),
            status_code=401,
        )

    @app.get("/logout")
    async def logout(request: Request) -> RedirectResponse:
        request.session.clear()
        return RedirectResponse(url="/login", status_code=302)

    @app.get("/", response_class=HTMLResponse, dependencies=[Depends(require_web_auth)])
    async def dashboard(
        request: Request,
        provider_sort: str = "count",
        provider_order: str = "desc",
        status_sort: str = "count",
        status_order: str = "desc",
    ) -> HTMLResponse:
        db_stats = database.get_stats()
        runtime = pipeline.runtime_stats()
        provider_sort = _normalize_sort_key(
            provider_sort, {"provider", "count"}, "count"
        )
        provider_order = _normalize_sort_order(provider_order)
        status_sort = _normalize_sort_key(status_sort, {"status", "count"}, "count")
        status_order = _normalize_sort_order(status_order)
        found_by_provider = sorted(
            db_stats["found_by_provider"],
            key=lambda row: row[provider_sort],
            reverse=provider_order == "desc",
        )
        status_breakdown = sorted(
            db_stats["status_breakdown"],
            key=lambda row: row[status_sort],
            reverse=status_order == "desc",
        )
        return _render(
            templates,
            request,
            "dashboard.html",
            db_stats={
                **db_stats,
                "found_by_provider": found_by_provider,
                "status_breakdown": status_breakdown,
            },
            runtime=runtime,
            provider_sort=provider_sort,
            provider_order=provider_order,
            status_sort=status_sort,
            status_order=status_order,
        )

    @app.get(
        "/keys/found",
        response_class=HTMLResponse,
        dependencies=[Depends(require_web_auth)],
    )
    async def found_keys(
        request: Request,
        page: int = 1,
        status: str = "",
        sort_by: str = "last_seen_at",
        sort_order: str = "desc",
    ) -> HTMLResponse:
        cfg = config_manager.get()
        page_size = max(1, cfg.web.page_size)
        offset = max(0, page - 1) * page_size
        effective_status = status.strip() or None
        sort_by = _normalize_sort_key(
            sort_by,
            {
                "id",
                "channel_name",
                "provider",
                "api_key",
                "repository",
                "file_path",
                "validation_status",
                "first_seen_at",
                "last_seen_at",
                "last_validated_at",
            },
            "last_seen_at",
        )
        sort_order = _normalize_sort_order(sort_order)
        rows = database.list_found(
            limit=page_size,
            offset=offset,
            status=effective_status,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        return _render(
            templates,
            request,
            "found_keys.html",
            rows=rows,
            page=page,
            status=status,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    @app.get(
        "/keys/validated",
        response_class=HTMLResponse,
        dependencies=[Depends(require_web_auth)],
    )
    async def validated_keys(
        request: Request,
        page: int = 1,
        provider: str = "",
        sort_by: str = "last_validated_at",
        sort_order: str = "desc",
    ) -> HTMLResponse:
        cfg = config_manager.get()
        page_size = max(1, cfg.web.page_size)
        offset = max(0, page - 1) * page_size
        provider_value = provider.strip() or None
        sort_by = _normalize_sort_key(
            sort_by,
            {"id", "provider", "api_key", "status", "last_validated_at", "detail"},
            "last_validated_at",
        )
        sort_order = _normalize_sort_order(sort_order)
        rows = database.list_validated(
            limit=page_size,
            offset=offset,
            provider=provider_value,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        return _render(
            templates,
            request,
            "validated_keys.html",
            rows=rows,
            page=page,
            provider=provider,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    @app.get(
        "/validation/logs",
        response_class=HTMLResponse,
        dependencies=[Depends(require_web_auth)],
    )
    async def validation_logs(
        request: Request,
        page: int = 1,
        status: str = "",
        sort_by: str = "validated_at",
        sort_order: str = "desc",
    ) -> HTMLResponse:
        cfg = config_manager.get()
        page_size = max(1, cfg.web.page_size)
        offset = max(0, page - 1) * page_size
        status_value = status.strip() or None
        sort_by = _normalize_sort_key(
            sort_by,
            {
                "id",
                "validated_at",
                "source",
                "channel_name",
                "provider",
                "api_key",
                "status",
                "detail",
            },
            "validated_at",
        )
        sort_order = _normalize_sort_order(sort_order)
        rows = database.list_validation_logs(
            limit=page_size,
            offset=offset,
            status=status_value,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        return _render(
            templates,
            request,
            "validation_logs.html",
            rows=rows,
            page=page,
            status=status,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    @app.get("/export/validated.csv", dependencies=[Depends(require_web_auth)])
    async def export_validated() -> FileResponse:
        with tempfile.NamedTemporaryFile(prefix="validated-", suffix=".csv", delete=False) as tmp:
            tmp_path = tmp.name
        database.export_validated_csv(tmp_path)
        return FileResponse(path=tmp_path, filename="validated_keys.csv", media_type="text/csv")

    @app.get(
        "/config", response_class=HTMLResponse, dependencies=[Depends(require_web_auth)]
    )
    async def config_page(request: Request) -> HTMLResponse:
        cfg = config_manager.get()
        channels_json = json.dumps([asdict(c) for c in cfg.channels], indent=2, ensure_ascii=False)
        validation_profiles_json = json.dumps(
            [asdict(p) for p in cfg.validation_profiles], indent=2, ensure_ascii=False
        )
        return _render(
            templates,
            request,
            "config.html",
            cfg=cfg,
            channels_json=channels_json,
            validation_profiles_json=validation_profiles_json,
            message="",
        )

    @app.post(
        "/config", response_class=HTMLResponse, dependencies=[Depends(require_web_auth)]
    )
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
        cfg.validation.revalidation_interval_seconds = int(
            _read_form_field(
                form_data,
                "revalidation_interval_seconds",
                str(cfg.validation.revalidation_interval_seconds),
            )
        )
        cfg.validation.pending_batch_size = int(
            _read_form_field(
                form_data, "pending_batch_size", str(cfg.validation.pending_batch_size)
            )
        )
        cfg.validation.validated_sample_size = int(
            _read_form_field(
                form_data,
                "validated_sample_size",
                str(cfg.validation.validated_sample_size),
            )
        )
        cfg.validation.ping_prompt = _read_form_field(
            form_data, "ping_prompt", cfg.validation.ping_prompt
        )
        cfg.validation.delete_invalid_keys = (
            _read_form_field(form_data, "delete_invalid_keys", "off") == "on"
        )

        cfg.web.host = _read_form_field(form_data, "web_host", cfg.web.host)
        cfg.web.port = int(_read_form_field(form_data, "web_port", str(cfg.web.port)))
        cfg.web.username = _read_form_field(form_data, "web_username", cfg.web.username)
        cfg.web.session_secret = _read_form_field(form_data, "web_session_secret", cfg.web.session_secret)
        cfg.web.page_size = int(_read_form_field(form_data, "web_page_size", str(cfg.web.page_size)))
        new_password = _read_form_field(form_data, "web_password")
        if new_password.strip():
            cfg.web.password_hash = normalize_secret_hash(new_password.strip())

        cfg.api.enabled = _read_form_field(form_data, "api_enabled", "off") == "on"
        new_api_token = _read_form_field(form_data, "api_token", "")
        if new_api_token.strip():
            cfg.api.token = normalize_secret_hash(new_api_token.strip())

        def _collect_indices(prefix: str) -> list[str]:
            indices = {
                key[len(prefix) :] for key in form_data.keys() if key.startswith(prefix)
            }

            def _sort_key(value: str) -> tuple[int, str]:
                return (0, value) if value.isdigit() else (1, value)

            return sorted(indices, key=_sort_key)

        use_json_profiles = (
            _read_form_field(form_data, "use_json_profiles", "off") == "on"
        )
        if not use_json_profiles:
            profile_indices = _collect_indices("profile_name_")
            validation_profiles: list[ValidationApiProfile] = []
            for idx in profile_indices:
                name = _read_form_field(form_data, f"profile_name_{idx}").strip()
                api_format = (
                    _read_form_field(form_data, f"profile_format_{idx}").strip().lower()
                )
                base_url = _read_form_field(
                    form_data, f"profile_base_url_{idx}"
                ).strip()
                path = _read_form_field(form_data, f"profile_path_{idx}").strip()
                if not (name and api_format and base_url and path):
                    continue
                headers_text = _read_form_field(
                    form_data, f"profile_headers_{idx}", "{}"
                )
                try:
                    headers_raw = (
                        json.loads(headers_text) if headers_text.strip() else {}
                    )
                except json.JSONDecodeError:
                    headers_raw = {}
                headers = (
                    {str(key): str(value) for key, value in headers_raw.items()}
                    if isinstance(headers_raw, dict)
                    else {}
                )
                models_text = _read_form_field(form_data, f"profile_models_{idx}")
                model_candidates = [
                    line.strip() for line in models_text.splitlines() if line.strip()
                ]
                validation_profiles.append(
                    ValidationApiProfile(
                        name=name,
                        api_format=api_format,
                        base_url=base_url,
                        path=path,
                        method=_read_form_field(
                            form_data, f"profile_method_{idx}", "POST"
                        )
                        .strip()
                        .upper()
                        or "POST",
                        headers=headers,
                        model_candidates=model_candidates,
                        api_key_transport=_read_form_field(
                            form_data, f"profile_key_transport_{idx}", "header"
                        )
                        .strip()
                        .lower()
                        or "header",
                        api_key_header=_read_form_field(
                            form_data, f"profile_key_header_{idx}", "Authorization"
                        ).strip()
                        or "Authorization",
                        api_key_prefix=_read_form_field(
                            form_data, f"profile_key_prefix_{idx}", "Bearer "
                        ),
                        api_key_query_param=_read_form_field(
                            form_data, f"profile_key_query_{idx}", "key"
                        ).strip()
                        or "key",
                        enabled=_read_form_field(
                            form_data, f"profile_enabled_{idx}", "off"
                        )
                        == "on",
                    )
                )
            cfg.validation_profiles = validation_profiles
        else:
            validation_profiles_text = _read_form_field(
                form_data, "validation_profiles_json", "[]"
            )
            validation_profiles_loaded = json.loads(validation_profiles_text)
            parsed_profiles: list[ValidationApiProfile] = []
            if isinstance(validation_profiles_loaded, list):
                for item in validation_profiles_loaded:
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("name", "")).strip()
                    api_format = str(item.get("api_format", "")).strip().lower()
                    base_url = str(item.get("base_url", "")).strip()
                    path = str(item.get("path", "")).strip()
                    if not (name and api_format and base_url and path):
                        continue
                    headers_raw = item.get("headers", {})
                    headers = (
                        {str(key): str(value) for key, value in headers_raw.items()}
                        if isinstance(headers_raw, dict)
                        else {}
                    )
                    model_candidates_raw = item.get("model_candidates", [])
                    model_candidates = (
                        [str(x).strip() for x in model_candidates_raw if str(x).strip()]
                        if isinstance(model_candidates_raw, list)
                        else []
                    )
                    parsed_profiles.append(
                        ValidationApiProfile(
                            name=name,
                            api_format=api_format,
                            base_url=base_url,
                            path=path,
                            method=str(item.get("method", "POST")).strip().upper()
                            or "POST",
                            headers=headers,
                            model_candidates=model_candidates,
                            api_key_transport=str(
                                item.get("api_key_transport", "header")
                            )
                            .strip()
                            .lower()
                            or "header",
                            api_key_header=str(
                                item.get("api_key_header", "Authorization")
                            ),
                            api_key_prefix=str(item.get("api_key_prefix", "Bearer ")),
                            api_key_query_param=str(
                                item.get("api_key_query_param", "key")
                            ),
                            enabled=bool(item.get("enabled", True)),
                        )
                    )
            if parsed_profiles:
                cfg.validation_profiles = parsed_profiles

        use_json_channels = (
            _read_form_field(form_data, "use_json_channels", "off") == "on"
        )
        if not use_json_channels:
            channel_indices = _collect_indices("channel_name_")
            channels: list[ChannelConfig] = []
            for idx in channel_indices:
                name = _read_form_field(form_data, f"channel_name_{idx}").strip()
                provider = (
                    _read_form_field(form_data, f"channel_provider_{idx}")
                    .strip()
                    .lower()
                )
                query = _read_form_field(form_data, f"channel_query_{idx}").strip()
                patterns_text = _read_form_field(form_data, f"channel_patterns_{idx}")
                extract_patterns = [
                    line.strip() for line in patterns_text.splitlines() if line.strip()
                ]
                if not (name and provider and query and extract_patterns):
                    continue
                channels.append(
                    ChannelConfig(
                        name=name,
                        provider=provider,
                        query=query,
                        extract_patterns=extract_patterns,
                        validation_profile=_read_form_field(
                            form_data, f"channel_profile_{idx}", "openai_compat"
                        ).strip()
                        or "openai_compat",
                        proxy=_read_form_field(
                            form_data, f"channel_proxy_{idx}", ""
                        ).strip(),
                        enabled=_read_form_field(
                            form_data, f"channel_enabled_{idx}", "off"
                        )
                        == "on",
                    )
                )
            cfg.channels = channels
        else:
            channels_text = _read_form_field(form_data, "channels_json", "[]")
            channels_loaded = json.loads(channels_text)
            parsed_channels: list[ChannelConfig] = []
            if isinstance(channels_loaded, list):
                for item in channels_loaded:
                    if not isinstance(item, dict):
                        continue
                    parsed_channels.append(
                        ChannelConfig(
                            name=str(item.get("name", "")).strip(),
                            provider=str(item.get("provider", "")).strip().lower(),
                            query=str(item.get("query", "")).strip(),
                            extract_patterns=[
                                str(x)
                                for x in item.get("extract_patterns", [])
                                if str(x).strip()
                            ],
                            validation_profile=str(
                                item.get("validation_profile", "openai_compat")
                            ).strip()
                            or "openai_compat",
                            proxy=str(item.get("proxy", "")),
                            enabled=bool(item.get("enabled", True)),
                        )
                    )
            cfg.channels = [
                c
                for c in parsed_channels
                if c.name and c.provider and c.query and c.extract_patterns
            ]

        config_manager.update(cfg)
        channels_json = json.dumps([asdict(c) for c in cfg.channels], indent=2, ensure_ascii=False)
        validation_profiles_json = json.dumps(
            [asdict(p) for p in cfg.validation_profiles], indent=2, ensure_ascii=False
        )
        return _render(
            templates,
            request,
            "config.html",
            cfg=cfg,
            channels_json=channels_json,
            validation_profiles_json=validation_profiles_json,
            message=_translate(_request_language(request), "config_saved"),
        )

    @app.post("/scan/run-now", dependencies=[Depends(require_web_auth)])
    async def run_now() -> RedirectResponse:
        pipeline.trigger_scan_now()
        return RedirectResponse(url="/", status_code=302)

    def _api_auth(token_provider: Callable[[], AppConfig], request: Request) -> None:
        cfg = token_provider()
        if not cfg.api.enabled:
            raise HTTPException(status_code=403, detail="api is disabled")
        token = request.headers.get("X-API-Token", "")
        if not verify_secret(token, cfg.api.token):
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
