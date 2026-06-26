# 第三方系统集成指南

让别的系统（如同机部署的 [Dataviewer](#案例dataviewer-同机集成)）一键把服务器上的轨迹文件送进 traj-lens 分析，**无需用户「下载再上传」**。

所有集成能力都是 **opt-in**——不配相关环境变量，则 traj-lens 行为与未集成时完全一致（向后兼容，独立部署不受影响）。

---

## 一图看懂

```
[ Dataviewer / 任意系统 ]                      [ traj-lens :18080 ]
  浏览到 foo.jsonl                                │
  └─ 调 GET /api/v1/integration ────────────────► 返回 {鉴权?, 允许根目录, 支持格式}
  └─ 调 POST /api/v1/ingest/path ───────────────► 同盘直读 foo.jsonl → 异步入库
        body: {path: "/data/.../foo.jsonl"}        └─ 返回 {job_id, dataset_id}
  └─ 轮询 GET /api/v1/jobs/{job_id} ────────────► done
  └─ 跳转 /trajlens/?dataset={dataset_id} ──────► 用户看到分析结果
```

---

## 三个集成能力

### 1. 自描述清单 `GET /api/v1/integration`

集成方第一步调它，一次拿到完整契约，不用猜：

```bash
curl http://HOST/api/v1/integration
```
```json
{
  "version": "1",
  "auth_required": false,
  "ingest_roots": ["/data/trajectories"],
  "formats": ["openai_messages", "claude_code", "codex", "swe_chat"],
  "endpoints": {
    "ingest_path": "POST /api/v1/ingest/path",
    "job_status": "GET /api/v1/jobs/{job_id}",
    "openapi": "/openapi.json"
  }
}
```

`auth_required` 告诉集成方要不要带 token；`ingest_roots` 告诉它能传哪些路径；`formats` 是当前支持的输入格式。完整 API 参考见 `/openapi.json`（FastAPI 自带 Swagger UI 在 `/docs`）。

### 2. 按服务器路径直读 ingest `POST /api/v1/ingest/path`

**同机同盘场景**：传文件的服务器绝对路径，traj-lens 直接读盘，零拷贝、异步。

```bash
curl -XPOST http://HOST/api/v1/ingest/path \
  -H 'Authorization: Bearer $TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{"path": "/data/trajectories/foo.jsonl"}'
```
```json
{ "job_id": "a1b2c3d4e5f6", "dataset_id": "ds_...", "dataset_name": "foo", "status": "pending" }
```

- **异步**：大文件（几千条轨迹）不阻塞，返回 `job_id`，轮询 `GET /api/v1/jobs/{job_id}` 看进度（`total` / `done` / `skipped` / `errors`）。
- **自动建数据集**：`dataset` 缺省 = 文件名 stem（`foo.jsonl` → 数据集 `foo`）；可显式传 `"dataset": "<name>"` 归到指定数据集。
- **返回 `dataset_id`**：集成方可立刻拼出跳转 URL（如 `/trajlens/?dataset=<id>`），用户点完「分析」直达结果页。
- **幂等**：同文件 ingest 多次安全（轨迹按 `content_hash` 去重，不会翻倍），集成方可无脑重试 → 「一次成功」。
- **格式自适应**：单 JSON 对象 / 整段 session log（CC、Codex）/ 逐行独立轨迹三种 shape 自动嗅探。

错误码：`403` 路径不在白名单或功能未开 · `404` 文件不存在 · `401` 鉴权失败 · `422` 缺 `path`。

### 3. 两个环境变量（控制开关 + 安全）

| 变量 | 作用 | 不配时 |
|---|---|---|
| `TRAJLENS_INGEST_ROOTS` | 冒号分隔的允许根目录（如 `/data/trajectories:/mnt/logs`）。路径直读必须 `resolve()` 后落在某个根下，否则 403——防 `../` 穿越。 | `/ingest/path` 一律 403（功能关闭） |
| `TRAJLENS_INGEST_TOKEN` | 配了则 `/ingest/path` 要求请求头 `Authorization: Bearer <token>`。 | 放行（无鉴权，与现状一致） |

> ⚠️ 路径直读会读服务器磁盘上白名单内的任意文件。生产环境**务必**同时配 `INGEST_ROOTS`（限定范围）和 `INGEST_TOKEN`（限定调用方）。

---

## 部署形态：反向代理到子路径（推荐）

**两个独立服务 + 一个域名**：traj-lens 保持独立进程（独立升级 / 回滚 / 重启，符合「单可部署物」），由前端站点的 nginx 反代到子路径，用户感知是「同一站点下的一个区域」，URL 统一、无丑端口。**不内嵌、不改子应用**——耦合两套构建/依赖/发布违背解耦目标。

前端所有 API 调用走 `import.meta.env.BASE_URL` 前缀，构建时设 `VITE_BASE` 即可挂到子路径，nginx 只需 plain `proxy_pass`、无需路径改写、不与宿主站的 `/api` 撞车：

```bash
# 构建带 /trajlens/ 前缀的前端（资源引用 + API 调用都带前缀）
cd web && VITE_BASE=/trajlens/ npm run build
```
```nginx
location /trajlens/ {
    proxy_pass http://127.0.0.1:18080/;
    proxy_read_timeout 120s;   # ingest 是异步 job，轮询不长连，超时主要兜 LLM 标注
}
```

独立部署时 `VITE_BASE` 不设（默认 `base=/`），前端 API 调 `/api/...`，一切照旧。

---

## 案例：Dataviewer 同机集成

Dataviewer（`dataview.rnd.com`）是数据盘的格式化 UI，能浏览文件夹、预览 jsonl；与 traj-lens 同机同盘。集成后用户流程：

**集成前**（5 步、含一次下载+上传往返）：Dataviewer 找到 jsonl → 下载到本机 → 进 `:18080` → 新建数据集 → 上传。

**集成后**（1 步、零拷贝）：Dataviewer 文件浏览器里 jsonl 旁点「用 traj-lens 分析」 → 后端调 `POST /ingest/path` 传绝对路径 → 跳转到 `dataview.rnd.com/trajlens/?dataset=<id>` 看结果。

Dataviewer 侧要做的：
1. 文件项加「用 traj-lens 分析」按钮，后端调 `POST /api/v1/ingest/path`（带 token，传文件服务器绝对路径），拿 `dataset_id`。
2. 轮询 `GET /api/v1/jobs/{job_id}` 到 `done`，跳转 `/trajlens/?dataset=<dataset_id>`。

traj-lens 服务器侧要做的：
1. 起服务时设 `TRAJLENS_INGEST_ROOTS=<数据盘根>` 和 `TRAJLENS_INGEST_TOKEN=<密钥>`。
2. 用 `VITE_BASE=/trajlens/ npm run build` 构建前端。
3. nginx 加上面的 `location /trajlens/` 反代。

---

## 给新集成方的最短清单

1. `GET /api/v1/integration` —— 读契约（要不要 token、能传哪些路径、支持哪些格式）。
2. `POST /api/v1/ingest/path` —— 传路径，拿 `job_id` + `dataset_id`。
3. 轮询 `GET /api/v1/jobs/{job_id}` —— 等 `status=done`。
4. 跳 `/<base>/?dataset=<dataset_id>` —— 看结果。

不在同一机器、无法共享磁盘？目前路径直读不适用——可先用现有 `POST /api/v1/datasets/{id}/upload`（multipart 上传）兜底；异机直读（内网 URL 拉取）是规划中的扩展，见 [docs/TODO.md](TODO.md) §11。
