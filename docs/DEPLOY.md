# 私有环境部署

traj-lens 是**单可部署物**：`trajlens serve` 同时提供 REST API 和托管前端（`web/dist`）。
没有外部服务依赖——存储是本地 SQLite（WAL）+ blob 目录。LLM 标注和 semgrep 扫描都是**可选**的，不配也能跑导入 / 浏览 / 指标 / 导出。

## 0. 前置

| 组件 | 版本 | 用途 |
|------|------|------|
| Python | 3.12+ | 后端运行时 |
| [uv](https://docs.astral.sh/uv/) | 最新 | 依赖管理 + 运行 |
| Node | 18+ | **仅构建前端时需要**，运行期不需要 |
| semgrep | 任意 | 可选——代码安全扫描，不装则该功能在 UI 显示「未安装」 |

> 离线机器：在有网机器上 `uv sync` + `npm run build`，把整个仓库目录（含 `.venv`、`web/dist`）打包拷过去即可。`web/dist` 是纯静态文件，运行期不再需要 Node。

## 1. 构建

```bash
git clone <repo> traj-lens && cd traj-lens
uv sync                                  # 安装 Python 依赖到 .venv
cd web && npm install && npm run build   # 产出 web/dist（serve 自动托管）
cd ..
```

构建后 `web/dist/index.html` 存在即代表前端就绪。`serve` 会探测该目录：存在则在 `/` 托管前端，不存在则只提供 API（详见 `src/trajlens/api/app.py` 的 `_mount_web`）。

> ⚠️ **从仓库根目录运行**。前端资源路径相对源码树解析（`web/dist` 与 `src/` 同级），且 `.env` 按**当前工作目录**读取（见 §2）。`pip install` 成 wheel 后这两点都会失效——目前只支持「源码目录内运行」这一拓扑。

## 2. 配置

所有配置走环境变量。`trajlens` 启动时读取**当前工作目录**下的 `.env`（stdlib 解析，已存在的环境变量优先，不覆盖）。

```bash
cp .env.example .env
```

| 变量 | 默认 | 说明 |
|------|------|------|
| `TRAJLENS_DB` | `trajlens.db` | SQLite 文件路径（相对 CWD 或绝对） |
| `TRAJLENS_BLOBS` | `blobs` | 原始字节 blob 目录 |
| `LLM_BASE_URL` | `https://api.openai.com/v1` | OpenAI 兼容端点；私有可填内网网关 |
| `LLM_API_KEY` | — | LLM 标注用，**不做标注可留空** |
| `LLM_MODEL` | `gpt-4o-mini` | 标注模型 |
| `LLM_PROXY` | `none` | `none` 或代理 URL |
| `LLM_RPS` / `LLM_MAX_CONCURRENCY` | `20` / `100` | LLM 请求限流 |

存储路径也可在命令行覆盖：`trajlens serve --db /data/trajlens.db --blob-dir /data/blobs`。`.env` 同时被 `ingest` / `annotate` / `metrics` / `export` / `serve` 读取——**务必在同一工作目录跑所有命令**，否则各命令可能指向不同 DB。

## 3. 运行

```bash
uv run trajlens serve --host 0.0.0.0 --port 8000
```

- `--host 0.0.0.0` 对外暴露（默认 `127.0.0.1` 仅本机）。
- **单进程运行，不要加多 worker**：存储是 SQLite WAL，单写者模型；多进程并发写会冲突。读多写少的分析负载下单进程足够，需要更高并发时换 Postgres 是另一回事（当前未支持）。
- `--reload` 仅用于开发。

### systemd（推荐生产托管方式）

```ini
# /etc/systemd/system/trajlens.service
[Unit]
Description=traj-lens
After=network.target

[Service]
WorkingDirectory=/opt/traj-lens          # 含 .env / .venv / web/dist 的仓库根
ExecStart=/usr/bin/uv run trajlens serve --host 0.0.0.0 --port 8000
Restart=on-failure
User=trajlens

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now trajlens
```

### 反向代理（可选，加 TLS / 鉴权）

应用自身**不做认证**。如需对外，前置 Nginx/Caddy 加 TLS + Basic Auth / SSO：

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    # 大轨迹导入：放宽 body 上限
    client_max_body_size 100m;
}
```

### Docker（可选）

```dockerfile
FROM node:18-slim AS web
WORKDIR /app/web
COPY web/package*.json ./
RUN npm install
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY . .
COPY --from=web /app/web/dist ./web/dist
RUN uv sync --frozen
# 可选安全扫描：RUN uv pip install semgrep
EXPOSE 8000
CMD ["uv", "run", "trajlens", "serve", "--host", "0.0.0.0", "--port", "8000"]
```

```bash
docker build -t traj-lens . && docker run -p 8000:8000 \
  -v $PWD/data:/app/data \
  -e TRAJLENS_DB=/app/data/trajlens.db -e TRAJLENS_BLOBS=/app/data/blobs \
  --env-file .env traj-lens
```

## 4. 数据 & 备份

两份真相：`TRAJLENS_DB`（分析数据 + 标注 + 指标）和 `TRAJLENS_BLOBS`（导入时的原始字节）。备份这两者即完整快照：

```bash
# 在线热备（WAL 安全）
sqlite3 trajlens.db ".backup '/backup/trajlens-$(date +%F).db'"
tar czf /backup/blobs-$(date +%F).tgz blobs/
```

恢复 = 拷回这两者，指向同一 `TRAJLENS_DB` / `TRAJLENS_BLOBS` 启动即可。

## 5. 升级

```bash
git pull
uv sync                          # 同步 Python 依赖
cd web && npm install && npm run build && cd ..   # 重建前端
sudo systemctl restart trajlens
```

DB schema 迁移在 `serve` 启动时自动执行（`app.py` 的 `dbmod.migrate`）——升级前备份 DB（§4）。

## 6. 冒烟验证

```bash
curl -s localhost:8000/api/v1/trajectories | head -c 200   # API 活着
curl -sI localhost:8000/ | grep -i content-type            # 前端被托管（text/html）
```

浏览器打开 `http://<host>:8000/` 看到轨迹列表即部署成功。
