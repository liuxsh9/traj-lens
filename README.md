# traj-lens

> Coding Agent 轨迹分析的底座平台：ingest 多样脚手架轨迹 → 统一中间格式 → 规则/LLM 标注 → 指标 → 可视化 → 挖掘/裁剪训练数据。

**状态**：设计阶段完成，骨架（slice 1）实现待启动。设计文档是当前唯一权威来源 → [docs/superpowers/specs/2026-06-21-traj-lens-design.md](docs/superpowers/specs/2026-06-21-traj-lens-design.md)。

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
