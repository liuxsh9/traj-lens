# traj-lens — 总进度

> 基于设计文档 `docs/superpowers/specs/2026-06-21-traj-lens-design.md` 各章节逐项展开。
> 每条对应设计中一个可交付能力，不是文件粒度。
> 更新日期：2026-06-23（slice-5 标注器+指标：error-recovery / intent / hard-interruption / tool_intensity）

---

## Slice 1 — 走通骨架（§9.4.1）

### 核心模型（§3）
- [x] Item 判别联合模型（message/reasoning/function_call/function_call_output） — `core/model.py`
- [x] Trajectory 数据结构（content_hash + items + tools + meta） — `core/model.py`
- [x] Provenance 出处指针（§3.4） — `core/model.py`
- [x] `parse_item()` 反序列化 — `core/model.py`

### 身份（§3.3）
- [x] `content_hash` 内容投影 + sha256，显式排除易变 meta — `core/identity.py`
- [x] `arguments` JSON key 排序归一化 — `core/identity.py`
- [x] `call_id` 从投影中排除（配对靠顺序） — `core/identity.py`

### step/run 分组投影（§3.5）
- [x] `assign_groups()` 确定性投影：step = think→act→observe 循环 — `core/grouping.py`
- [x] 单 user prompt → N step（不塌成 2 卡）— 真实 113 消息样本验证通过

### 注册表（§5.3）
- [x] 通用 `Registry`（dict + 重复守卫） — `core/registry.py`

### 适配器（§5.2 ①）
- [x] `openai_messages` adapter：OpenAI ChatCompletions / panguml2 → Trajectory — `adapters/openai_messages.py`
- [x] `detect_and_parse()` 嗅探+注册表 — `adapters/__init__.py`
- [x] Claude Code 原始日志 adapter — `adapters/claude_code.py`
- [x] Codex adapter — `adapters/codex.py`
- [x] SWE-chat adapter（JSON rows→items）— `adapters/swe_chat.py`

### 存储（§6 + §10.C.8/9）
- [x] SQLite WAL + busy_timeout + synchronous=NORMAL — `store/db.py`
- [x] `PRAGMA user_version` 极简迁移 runner — `store/db.py`
- [x] 001_init.sql：trajectories / ingestions / raw_blobs / items — `store/migrations/`
- [x] `put_trajectory` 按 content_hash 去重，ingestion 多对一 — `store/repo.py`
- [x] `get_trajectory` 读时带 step/run 分组 — `store/repo.py`
- [x] `list_trajectories` — `store/repo.py`
- [x] raw blob 磁盘存储 — `store/repo.py`
- [ ] §10.C.8 单写者纪律（专用 writer 连接串行化，`BEGIN IMMEDIATE`）— slice 2 异步 runner 时上
- [ ] §10.B.4 预留 `artifacts` 旁表（diff/commit/snapshot）

### API（§5.2 ⑧ + §11）
- [x] `POST /api/v1/trajectories` 幂等 ingest — `api/routes.py`
- [x] `GET /api/v1/trajectories` 列表 — `api/routes.py`
- [x] `GET /api/v1/trajectories/{hash}` 详情（items+grouping DTO）— `api/routes.py`
- [x] `GET /api/health` — `api/routes.py`
- [ ] API 版本化前缀 `/api/v1` 的 Router 组织（当前已满足，路由拆分留到路由增多时）
- [x] FastAPI StaticFiles 托管打包 web（单可部署物 `trajlens serve`）— `api/app.py` SPA fallback
- [ ] 批量 ingest 端点（inline 多条）
- [ ] OpenAPI schema 导出 / Swagger UI 验证

### CLI（§9.1）
- [x] `trajlens ingest`（JSON 单对象 + JSONL）— `cli.py`
- [x] `trajlens serve` — `cli.py`
- [x] `trajlens annotate <config.yaml>` — `cli.py`
- [ ] `trajlens export` — slice 4

### Web — 最小线性 viewer（§12.2 A 层）
- [x] Vite + React + TS 项目骨架 — `web/`
- [x] dev proxy `/api` → FastAPI — `web/vite.config.ts`
- [x] 语料列表页（hash / items_count / created_at） — `web/src/App.tsx`
- [x] 单轨迹线性转录视图：按 item 类型着色、gutter 显示 run/step — `web/src/components/TrajectoryView.tsx`
- [x] 暗色 CSS 主题（mockup 配色复用）— `web/src/styles.css`
- [x] `npm run build` 产物被 FastAPI serve（StaticFiles 托管）

### 测试 & 样本
- [x] core 单测：model / identity / grouping / registry — 12 tests
- [x] adapter + store + api + cli 集成测 — 14 tests
- [x] 真实数据样本语料（9 openai_messages + 17 swe_chat fixtures, EN/ZH/KO/PT/RU）— `tests/samples/`
- [x] 兼容性回归 `test_samples.py`（全样本走 adapter→grouping→store 往返）

---

## Slice 2 — 标注中间件（§9.4.2）

### 标注器接口（§7.1）
- [x] `AnnotatorSpec` 数据类（id / target / context / version） — `annotate/__init__.py`
- [x] `Target` 枚举：SESSION / USER_TURN / ASSISTANT_TURN / STEP / TOOL_RESULT
- [x] `ContextPolicy` 解析：self / window:k / prefix / whole
- [x] `RuleAnnotator` 协议（`annotate(unit, ctx) -> Value`）
- [x] `LLMAnnotator` 协议（`build(unit, ctx) -> messages` / `parse(resp) -> Value`）

### 标注版本（§4）
- [x] `annotator_version` 自动派生（sha256(type+config)[:12]）— `annotate/__init__.py`
- [x] 缓存键 `(target_hash, annotator_id, version)` — `runner.py` + `002_annotations.sql`
- [x] 多版本共存 + `active_version` 指针 — `annotators` 表 active 列
- [ ] §10.B.6 版本覆盖率查询

### 标注存储
- [x] `annotations` 表 migration — `002_annotations.sql`
- [x] `annotators` 版本台账表 migration
- [x] annotation CRUD（put 幂等 / get / query by target+annotator+version）— `repo.py`

### Runner（§7.3）
- [x] 幂等并发 runner（按 target 枚举、按 context 投影、cache hit 跳过、asyncio.gather 并发 LLM）— `runner.py`
- [x] `jobs` 表 + 进度/错误追踪
- [x] 失败隔离（FatalError 记录，不中断批次）
- [x] §10.C.8 单写者纪律（`BEGIN IMMEDIATE` + `put_annotation`）

### 可靠 LLM 客户端（§7.4）
- [x] profile 化配置（`config/llm_profiles.yaml` + `${ENV}` 引用）— `llm_client.py`
- [x] OpenAI 兼容 client（httpx async, base_url + key + model）
- [x] 指数退避重试（429/5xx/timeout, 4xx 快速失败, max 4次）
- [x] 全局信号量限流
- [x] 结构化输出（json_schema+strict 优先, fallback parse+repair）
- [x] 可观测：logging tokens/延迟
- [x] 代理三模式：none / system / explicit URL

### YAML 配置加载（§7.2）
- [x] `config/annotators/*.yaml` loader — `runner.py: load_annotator_config`
- [x] `config/llm_profiles.yaml` loader — `llm_client.py: load_profiles`
- [x] 配置变更 → version 自动变 — `compute_version`

### 首批标注器
- [x] `loop_detect` rule 标注器（STEP 级，同文件编辑 ≥3）— `annotate/rules/loop_detect.py`
- [x] `pushback` LLM 标注器（USER_TURN 级，correction/rejection/failure_report）— `annotate/llm/pushback.py`
- [x] `resolution` LLM 标注器（SESSION 级，resolved/partially/unresolved/indeterminate）— `annotate/llm/resolution.py`
- [x] `topic` LLM 标注器（SESSION 级，中文标题+客观摘要+类型标签）— `annotate/llm/topic.py`

### API 扩展
- [x] `POST /api/v1/jobs`（建标注任务，后台线程执行）— `routes.py`
- [x] `GET /api/v1/jobs/{id}`（进度/错误）
- [x] `GET /api/v1/trajectories/{hash}` 返回中叠加 annotations
- [ ] `GET /api/v1/catalog/annotators`（id / target / schema / active_version）

### CLI 扩展
- [x] `trajlens annotate <config.yaml>` — `cli.py`

### Web 扩展
- [x] viewer 中展示标注 chip — `TrajectoryView.tsx`

### §10.B.5 依赖一等声明
- [ ] spec 中 `depends_on` 字段 + 一趟拓扑排序

---

## Slice 3 — 指标 + 浏览（§9.4.3）

### 指标（§5.2 ⑥）
- [x] metric 接口 + 注册表 — `metrics/__init__.py`（decorator registry + compute_metrics runner）
- [x] 内置 metrics：pushback_count / turn_count / step_count / tool_count — `metrics/builtins.py`
- [x] session-level success 评分（rule-based: resolution baseline − pushback penalty）— `metrics/builtins.py:success_score`
- [ ] 效率指标（token/cost per 100 committed lines）— 需 artifacts
- [ ] 安全指标（Semgrep diff）— 需 artifacts
- [x] `metrics` 表 migration + CRUD — `003_metrics.sql` + `repo.py`
- [x] §4.3 指标 provenance + 陈旧感知 — `_effective_version` compound key（metric version + dep annotator versions），自动检测依赖变更并 recompute
- [x] 标注完成后自动失效依赖指标缓存 — `runner.py:_invalidate_dependent_metrics`

### 列表浏览
- [x] API：`GET /api/v1/trajectories` 返回 metrics + session annotations — `routes.py`
- [x] Web：TanStack Table 排序/筛选/分页 — `App.tsx`（client-side sort + resolution filter）
- [x] Web：TanStack Query 替换手写 fetch — `main.tsx` QueryClientProvider

### CLI
- [x] `trajlens metrics` — 计算所有轨迹的指标 — `cli.py`

---

## Slice 4 — 数据集管理 + 导入导出闭环（§8 + §9.4.4）

### 数据集管理
- [x] Dataset / Batch 数据模型 + migration — `004_datasets.sql`
- [x] Dataset CRUD（create / get / list / delete）— `repo.py`
- [x] Batch CRUD + put_trajectory 归批 — `repo.py`
- [x] `detect_and_parse` 返回格式名 → batch.format — `adapters/__init__.py`
- [x] CLI `ingest --dataset` 自动建数据集+批次 — `cli.py`
- [x] API 数据集端点（POST/GET/DELETE datasets, GET batches）— `routes.py`
- [x] Web 三层导航：Dataset Wall → Dataset Detail → Trajectory Viewer — `App.tsx`
- [x] Dataset 卡片墙首页 — `DatasetWall.tsx`
- [x] Dataset 详情页（header + batch chips + 列表）— `DatasetDetail.tsx`
- [x] 按数据集过滤轨迹（query_trajectories 支持 dataset_id 作用域）— `repo.py`

### 统计仪表板
- [x] 数据集聚合统计查询（指标汇总 + resolution 分布 + tags + 批次对比）— `repo.py:get_dataset_stats`
- [x] 统计 API 端点 — `GET /api/v1/datasets/{id}/stats`
- [x] Web 统计面板（摘要卡片 + resolution 分布条 + 指标概览 + tags）— `DatasetDetail.tsx:StatsPanel`

### 裁剪（§8.2–8.3）
- [x] `validate_trim(items, start, end)` R1–R4 四条校验 — `export/trim.py`
- [ ] §10.A.1 R3 续接守卫增强（非续接 or turn0 自足）
- [ ] mask（per-atom weight=0，导出时写入，不改 canonical）
- [ ] trim + mask 叠加

### 导出器（§8.5–8.6）
- [x] exporter 注册表 — `export/__init__.py`
- [x] panguml2 SFT jsonl 导出器（字节保真 + 转换 fallback）— `export/panguml2.py`
- [x] `ExportArtifact` 追溯 — `005_exports.sql` + `repo.py`
- [x] provenance 写入 panguml2 `meta_info`（content_hash + export_mode）
- [ ] 偏好对 jsonl 导出器

### 选择（§8.1）
- [ ] `Selection` 模型（predicate + pinned_versions + members）
- [ ] A/B/C 三类预设配方

### 偏好对（§8.4）
- [ ] B 类构造：shared_prefix / rejected / chosen / correction_text
- [ ] continuation 过滤守卫（turn_number > 首个 agent 行为）

### API + CLI
- [x] `POST /api/v1/exports` — `routes.py`
- [x] `trajlens export <dataset>` CLI — `cli.py`

### Web
- [ ] viewer 内 trim/mask 交互（左缘勾选 + 底部 R1–R4 实时校验）
- [ ] 导出按钮 + 进度（DatasetDetail 内）

---

## 富 Viewer — B+C hybrid（§12，在 slice 2 之后自成切片）

### 布局
- [x] minimap 左栏（每 atom 一 tick，pushback flag 标记）— `Minimap.tsx`
- [x] 折叠 step 卡（信号头：actor + 摘要 + 工具足迹 tool→tool→tool chain）— `CardStack.tsx`
- [x] run group 可整体折叠（run 头：步数 + 工具 chain）— `CardStack.tsx`
- [x] 展开 = typed-item 转录（A 层复用）— `ItemTranscript.tsx`
- [x] pinned bookend：顶部 TASK（首条 user）+ 底部 REPLY（末条 assistant），可折叠 — `CardStack.tsx`

### 折叠策略（§12.5）
- [x] run 展开、step 默认折叠；折叠全部只折叠 step 不折叠 run — `TrajectoryViewer.tsx`
- [x] pushback user turn 红色高亮 + chip 标注 — `CardStack.tsx`

### 标注叠加（§12.6）
- [x] pushback turn chip（category 标签）— `CardStack.tsx`
- [x] session header 显示 topic 标题/摘要/tags + 分数/指标 — `SessionHeader.tsx`
- [x] topic LLM 标注器（中文标题+摘要+类型标签）— `annotate/llm/topic.py`
- [ ] turn/step chip 带 @version
- [ ] 陈旧 badge（`v2 ready → 刷新？`）

### 列表浏览增强
- [x] 轨迹列显示 topic 标题 + hash + tags — `ListView.tsx`
- [x] 多维度筛选器（resolution / score / pushback / turn count）— `ListView.tsx`
- [x] 分页 + 排序 — `ListView.tsx`

### trim/mask 交互（§12.7）
- [ ] 左缘勾选选区 + 底部 R1–R4 实时校验
- [ ] per-step mask weight=0

### 技术
- [ ] react-window 虚拟化（长 run >200 步时）
- [ ] d3 仅时间线/热力图（按需）

---

## Slice 5 — 铺广度（§9.4.5）

### 更多 adapter
- [x] Claude Code 原始日志 adapter — done in slice 1
- [x] Codex adapter — done in slice 1
- [x] SWE-chat adapter — done in slice 2
- [ ] 自研脚手架 adapter

### 更多标注器
- [x] intent（5 类，LLM，USER_TURN：implement/debug/refactor/explain/other）— `annotate/llm/intent.py`
- [ ] persona（4 类，LLM，USER_TURN）— 暂缓，信号不可靠
- [x] hard-interruption 检测（rule，SESSION 级）— `annotate/rules/hard_interruption.py`
- [x] error-recovery 检测（rule，STEP 级）— `annotate/rules/error_recovery.py`

### 新增指标
- [x] tool_intensity metric（calls / unique_tools / error_steps / recovery_rate）— `metrics/builtins.py`

### 代码级信号（§1 可选 analyzer）
- [ ] §10.B.4 artifacts 表实装
- [ ] code-survival metric（行级人/机归因，需 commit 输入）
- [ ] committed lines 计数（效率分母）
- [ ] Semgrep pre/post 安全扫描（agent 引入漏洞数 = post findings − pre baseline）

### 工具调用代码可观测（从轨迹中提取代码变更）
- [ ] 从 function_call（write/edit/bash）中提取代码 diff / 配置变更
- [ ] Semgrep 对提取的代码片段做安全扫描（不依赖 artifacts，直接分析轨迹内工具输出）
- [ ] HTML/SVG/Mermaid 等可视化语言外置预览（viewer 内 iframe sandbox 渲染）
- [ ] 代码变更时间线（哪个 step 改了哪个文件，变更类型分类：新建/修改/删除/配置）

### 可集成性（§11）
- [ ] API-key 可选鉴权
- [ ] 批量 ingest（inline 多条）
- [ ] webhook 回调（job 完成时 HMAC 签名推送）

---

## 基础设施 & 运维

### 运行（§9.5）
- [ ] FastAPI StaticFiles 托管打包 web = 单可部署物
- [ ] launchd plist（macOS 本地常驻）
- [ ] systemd unit（Linux）
- [ ] my-toolbox 门户注册

### 工程
- [x] pyproject.toml + uv.lock
- [x] .gitignore
- [x] README.md
- [x] 设计文档 + viewer mockups
- [x] 实现计划（slice-1）
- [x] 测试样本语料 + 兼容性回归
- [x] CI（GitHub Actions：pytest + tsc + build）— `.github/workflows/ci.yml`
- [x] CLAUDE.md 项目级指令

---

## 统计

| 分类 | 总计 | 完成 | 进度 |
|---|---|---|---|
| Slice 1 骨架 | 35 | 34 | **97%** |
| Slice 2 标注 | 29 | 28 | **97%** |
| Slice 3 指标+浏览 | 12 | 10 | **83%** |
| Slice 4 数据集+导出 | 22 | 16 | **73%** |
| 富 Viewer | 17 | 13 | **76%** |
| Slice 5 铺广度 | 17 | 7 | 41% |
| 基础设施 | 12 | 8 | 67% |
| **合计** | **144** | **116** | **81%** |
