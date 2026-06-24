# traj-lens

> Coding Agent 轨迹分析的底座平台：ingest 多样脚手架轨迹 → 统一中间格式 → 规则/LLM 标注 → 指标 → 可视化 → 挖掘/裁剪训练数据。

**状态**：slice ①–⑤ 已落地（ingest / 标注中间件 / 指标 + 浏览 / 挑数据导出 / semgrep 安全扫描），可端到端运行。设计权威来源 → [docs/superpowers/specs/2026-06-21-traj-lens-design.md](docs/superpowers/specs/2026-06-21-traj-lens-design.md)。

## 快速开始（本地 / 私有环境）

```bash
# 1. 依赖（需要 uv + Python 3.12，前端需要 Node 18+）
uv sync
cd web && npm install && npm run build && cd ..   # 产出 web/dist，serve 自动托管

# 2. 配置（LLM 标注 + 存储路径）
cp .env.example .env && $EDITOR .env

# 3. 跑起来：导入一条轨迹 → 起服务
uv run trajlens ingest tests/samples/claude_code/<some>.jsonl
uv run trajlens serve            # http://127.0.0.1:8000 （API + 前端同一可部署物）
```

**监听地址与端口**：默认只听本机 `127.0.0.1:8000`。部署到服务器、需要内网/局域网访问时，在 `.env` 设 `TRAJLENS_HOST=0.0.0.0`、按需改 `TRAJLENS_PORT`；命令行 `--host` / `--port` 优先级更高，可临时覆盖：

```bash
uv run trajlens serve --host 0.0.0.0 --port 9000   # 等价于在 .env 配置后直接 serve
```

> 私有环境完整部署（离线、systemd/Docker、反代、备份、可选 semgrep）→ **[docs/DEPLOY.md](docs/DEPLOY.md)**。

## 它做什么

Claude Code / Codex / OpenCode 等 Coding Agent = **LLM + 脚手架**。traj-lens 观测并分析这一过程的轨迹：

- **统一中间格式**：多样输入（CC jsonl / Codex / panguml2 训练数据 / 自研…）→ 两层内容寻址模型（raw 字节真相 + Items-canonical 分析真相，OpenAI Responses 风格 typed items）+ 出处指针。
- **标注与分析**：规则/LLM 标注器，session / turn / **step** 级；可靠的 OpenAI 兼容 LLM 中间件（重试 / 限流 / 缓存 / 结构化输出 / 配置化 prompt+profile）。
- **指标与浏览**：跨语料排序 / 筛选 / 下钻。
- **可视化**：单轨迹 viewer —— minimap 全局形状 + 可折叠 step 卡 + 展开 typed-item 转录（设计 §12，草图见 [`mockups/`](mockups/)）。
- **训练数据挖掘**：按训练价值选择 + 裁剪（**只裁不改写、保证完整性 R1–R4**）+ 导出（panguml2 SFT / 偏好对），用于 SFT / 退火回流。

> 验收基准：完整承载 swe-chat（arXiv:2604.20779）的轨迹分析能力，并具更优扩展性。

## 扩展点 = 四注册表（in/out 对称）

```
输入 adapters(in) ──► [ annotators · metrics ] ──► 导出 exporters(out)
```

加输入 / 加标注 / 加指标 / 加导出格式 = 注册一个新函数（LLM 标注器甚至只是一个 yaml），core 不动。

## 技术栈

Python 3.12+（uv）· Pydantic v2 · FastAPI · stdlib `sqlite3` · 官方 `openai` SDK · React + Vite + Tailwind + TanStack。单仓库、单可部署物（`trajlens serve` 同时供 API + 托管前端）。

## 仓库结构（规划，见设计 §9.1）

```
config/        # llm_profiles.yaml · annotators/*.yaml
src/trajlens/  # core · adapters · store · annotate · llm · metrics · export · api · cli
web/           # Vite + React viewer
docs/          # 设计文档（spec，权威来源）
mockups/       # viewer 设计草图
tests/
```

## 实施切片（设计 §9.4，每片端到端可跑）

① 走通骨架 → ② 标注中间件 → ③ 指标 + 浏览 → ④ 挑数据闭环 → ⑤ 铺广度。富 viewer 在 ② 之后自成切片。
