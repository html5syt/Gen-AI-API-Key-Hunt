# GitHub LLM Key Searcher

一个完整的 GitHub LLM Key Searcher：支持后台常驻扫描、发现与验证并行、WebUI 管理后台、API 拉取已验证 keys、Docker 部署，以及配置文件/GUI 双向配置。

## 主要功能

- **查找与验证并行**：扫描任务发现 key 后立即进入验证队列，后台并发验证。
- **WebUI 后台（可配置端口）**：
  - 登录鉴权（用户名+密码）
  - 查看已找到 keys / 已验证 keys
  - 批量导出已验证 keys（CSV）
  - 数据看板（总量、状态分布、按 provider 统计）
- **API 接口**：通过 Token 鉴权获取已验证 keys 与统计数据。
- **配置文件替代环境变量**：全部核心参数统一在 `config.yaml`，并支持在 GUI 在线修改。
- **后台常驻扫描 + 扫描周期可配**：默认按周期持续扫描，也支持手动立即触发。
- **渠道级独立代理**：每个渠道单独配置 `proxy`。
- **自定义渠道与搜索表达式**：可在 GUI 的渠道 JSON 配置中自定义 provider/query/regex。
- **Docker 镜像支持**：可直接容器化运行。

## 项目结构

```text
app/
  config.py        # 配置模型与读写
  database.py      # SQLite 存储与查询
  searcher.py      # GitHub 搜索
  validator.py     # Provider key 验证
  pipeline.py      # 扫描调度、搜索/验证并行流水线
  web.py           # FastAPI WebUI + API
  main.py          # 启动入口
  templates/       # WebUI 模板
search_keys.py     # 兼容入口（启动新系统）
validate_keys.py   # 兼容入口（启动新系统）
```

## 快速开始

### 1) 安装依赖

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2) 初始化配置

```bash
cp config.yaml.example config.yaml
```

编辑 `config.yaml`，至少填入：

- `github.tokens`
- `web.username` / `web.password_hash`
- `web.session_secret`
- `api.token`

> 默认密码 hash 对应 `admin`，建议立即修改。

### 3) 启动

```bash
python -m app.main --config config.yaml --db data/app.db
```

启动后访问：`http://<host>:<port>`（默认 `http://127.0.0.1:8080`）

## WebUI 功能

- `/login` 登录
- `/` 数据看板
- `/keys/found` 查看已找到 keys
- `/keys/validated` 查看已验证 keys
- `/export/validated.csv` 导出 CSV
- `/config` 在线修改配置（包括扫描周期、渠道表达式、渠道代理等）

## API

请求头：`X-API-Token: <api.token>`

- `GET /api/v1/validated-keys?limit=100&offset=0&provider=`
- `GET /api/v1/stats`

## Docker

### 构建

```bash
docker build -t github-llm-key-searcher:latest .
```

### 运行

```bash
docker run --rm -p 8080:8080 \
  -v $(pwd)/config.yaml:/app/config.yaml \
  -v $(pwd)/data:/app/data \
  github-llm-key-searcher:latest
```

## 安全提示

- 请仅用于授权范围内的安全研究与自检。
- Web 密码请使用强口令（存储为 SHA256 hash）。
- API Token 请设置高强度随机值并妥善保管。
- 渠道配置支持自定义表达式，请谨慎配置避免误采集。

## 许可证

MIT
