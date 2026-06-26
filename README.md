# traj-lens

> Coding Agent 轨迹分析的底座平台：ingest 多样脚手架轨迹 → 统一中间格式 → 规则/LLM 标注 → 指标 → 可视化 → 挖掘/裁剪训练数据。

Claude Code / Codex / OpenCode 等 Coding Agent = **LLM + 脚手架**。traj-lens 把它们运行过程产生的多样轨迹，归一成一套可标注、可度量、可视化、可导出训练数据的中间模型。一句话：**给 Coding Agent 的轨迹做「显微镜 + 数据车间」**。

**当前能力**（端到端可跑）：多格式 ingest · 规则/LLM 标注中间件 · 指标与跨语料浏览 · 单轨迹富 viewer · semgrep 安全扫描 · 挑数据裁剪导出（panguml2 SFT）· 第三方系统集成（按服务器路径直读 ingest）。

---

## 快速开始（本地 / 私有环境）

```bash
# 1. 依赖（需 uv + Python 3.12；前端需 Node 18+）
uv sync
cd web && npm install && npm run build && cd ..   # 产出 web/dist，serve 自动托管

# 2. 配置（LLM 标注 + 存储路径）
cp .env.example .env && $EDITOR .env

# 3. 跑起来：导入一条轨迹 → 起服务
uv run trajlens ingest tests/samples/claude_code/<some>.jsonl
uv run trajlens serve            # http://127.0.0.1:8000 （API + 前端，单一可部署物）
```

默认只听 `127.0.0.1:8000`。要内网/局域网访问，在 `.env` 设 `TRAJLENS_HOST=0.0.0.0`、按需改 `TRAJLENS_PORT`（命令行 `--host` / `--port` 优先级更高）。

```bash
uv run trajlens serve --host 0.0.0.0 --port 9000
```

`serve` 启动时若发现 `web/dist` 比前端源码旧，会自动重建（`--no-build` 跳过）。

---

## 文档地图

看完这张表就知道每件事的细节去哪找：

| 想做什么 | 去哪 |
|---|---|
| **了解项目是什么、跑起来** | 本文件（你在这） |
| **私有环境部署**（离线 / systemd·Docker / 反代 / 备份 / semgrep） | [docs/DEPLOY.md](docs/DEPLOY.md) |
| **把别的系统接进来**（路径直读 ingest / 鉴权 / 子路径部署 / Dataviewer 案例） | [docs/INTEGRATION.md](docs/INTEGRATION.md) |
| **设计权威来源**（模型 / 身份 / 分组 / 各章节决策） | [docs/superpowers/specs/2026-06-21-traj-lens-design.md](docs/superpowers/specs/2026-06-21-traj-lens-design.md) |
| **当前进度 / 未完成项 / 取舍记录** | [docs/TODO.md](docs/TODO.md) |
| **改代码前必读**（架构约定 / 多 agent 协作 / 提交规范 / 调试 cheatsheet） | [CLAUDE.md](CLAUDE.md) |
| **完整 API 参考** | 启动后访问 `/docs`（Swagger UI）或 `/openapi.json` |
| **viewer 设计草图** | [mockups/](mockups/) |

---

## 它做什么

- **统一中间格式**：多样输入（CC jsonl / Codex / panguml2 训练数据 / SWE-chat / 自研…）→ 两层内容寻址模型（raw 字节真相 + Items-canonical 分析真相，OpenAI Responses 风格 typed items）+ 出处指针。
- **标注与分析**：规则/LLM 标注器，session / turn / **step** 级；可靠的 OpenAI 兼容 LLM 中间件（重试 / 限流 / 缓存 / 结构化输出 / 配置化 prompt+profile）。
- **指标与浏览**：跨语料排序 / 筛选 / 下钻。
- **可视化**：单轨迹 viewer —— minimap 全局形状 + 可折叠 step 卡 + 展开 typed-item 转录。
- **训练数据挖掘**：按训练价值选择 + 裁剪（**只裁不改写、保证完整性 R1–R4**）+ 导出（panguml2 SFT / 偏好对），用于 SFT / 退火回流。

> 验收基准：完整承载 SWE-chat（arXiv:2604.20779）的轨迹分析能力，并具更优扩展性。

## 架构：扩展点 = 四注册表（in/out 对称）

```
输入 adapters(in) ──► [ annotators · metrics ] ──► 导出 exporters(out)
```

加输入 / 加标注 / 加指标 / 加导出格式 = 注册一个新函数（LLM 标注器甚至只是一个 yaml），core 不动。这也是接入新轨迹格式的入口——每个 adapter 只需实现 `sniff(raw)->bool` + `parse(raw)->Trajectory`。

```
config/        # llm_profiles.yaml · annotators/*.yaml
src/trajlens/  # core · adapters · store · annotate · llm · metrics · export · api · cli
web/           # Vite + React viewer
docs/          # 设计 spec（权威）· DEPLOY · INTEGRATION · TODO
tests/         # 单测 + 真实样本语料（兼容性回归）
```

## 第三方系统集成（概览）

让同机系统一键把服务器上的轨迹文件送进来分析，无需「下载再上传」。核心是三个 **opt-in** 能力（不配环境变量则行为与今天完全一致）：

- `GET /api/v1/integration` —— 自描述清单，集成方一次拿到契约（鉴权 / 允许根目录 / 支持格式）。
- `POST /api/v1/ingest/path` —— 传服务器绝对路径，同盘直读、异步入库、按文件名建数据集、幂等可重试、返回 `dataset_id` 供跳转。
- `TRAJLENS_INGEST_ROOTS`（路径白名单防穿越）+ `TRAJLENS_INGEST_TOKEN`（Bearer 鉴权）。

→ 完整指南、子路径反代部署、Dataviewer 集成案例：**[docs/INTEGRATION.md](docs/INTEGRATION.md)**

## 技术栈

Python 3.12+（uv）· Pydantic v2 · FastAPI · stdlib `sqlite3` · 官方 `openai` SDK · React + Vite + TanStack。单仓库、单可部署物（`trajlens serve` 同时供 API + 托管前端）。
