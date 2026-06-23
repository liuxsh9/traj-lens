# traj-lens — 总进度

> 基于设计文档 `docs/superpowers/specs/2026-06-21-traj-lens-design.md` 各章节逐项展开。
> 每条对应设计中一个可交付能力，不是文件粒度。
> 更新日期：2026-06-22（slice-2 二次收尾：resolution 标注器 + prompt 调优 + 测试集扩充）

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
- [x] 幂等并发 runner（按 target 枚举、按 context 投影、cache hit 跳过）— `runner.py`
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
- [ ] metric 接口 + 注册表
- [ ] 内置 metrics：pushback_count / turn_count / step_count / tool_count
- [ ] session-level success 评分（LLM judge，depends_on pushback）
- [ ] 效率指标（token/cost per 100 committed lines）— 需 artifacts
- [ ] 安全指标（Semgrep diff）— 需 artifacts
- [ ] `metrics` 表 migration + CRUD
- [ ] §4.3 指标 provenance + 陈旧感知

### 列表浏览
- [ ] API：`GET /api/v1/trajectories?filter=&sort=&page=`（join metrics+annotations）
- [ ] Web：TanStack Table 排序/筛选/分页
- [ ] Web：TanStack Query 替换手写 fetch（此时 >2 个端点，值得引入）

---

## Slice 4 — 挑数据闭环（§9.4.4）

### 选择（§8.1）
- [ ] `Selection` 模型（predicate + pinned_versions + members）
- [ ] 结构化过滤谓词 → SQLite 查询
- [ ] A/B/C 三类预设配方

### 裁剪（§8.2–8.3）
- [ ] `validate_trim(traj, a, b)` 四条校验（R1 边界 / R2 工具配对 / R3 上文完整 / R4 结尾可训）
- [ ] §10.A.1 R3 续接守卫增强（非续接 or turn0 自足）
- [ ] mask（per-atom weight=0，导出时写入，不改 canonical）
- [ ] trim + mask 叠加

### 偏好对（§8.4）
- [ ] B 类构造：shared_prefix / rejected / chosen / correction_text
- [ ] continuation 过滤守卫（turn_number > 首个 agent 行为）

### 导出器（§8.5–8.6）
- [ ] exporter 注册表
- [ ] panguml2 SFT jsonl 导出器（字节保真模式）
- [ ] 偏好对 jsonl 导出器
- [ ] `ExportArtifact` 追溯（selection + trim_spec + exporter + pinned_versions）
- [ ] provenance 写入 panguml2 `meta_info`

### API + CLI
- [ ] `POST /api/v1/exports`
- [ ] `trajlens export` CLI

### Web
- [ ] viewer 内 trim/mask 交互（左缘勾选 + 底部 R1–R4 实时校验）

---

## 富 Viewer — B+C hybrid（§12，在 slice 2 之后自成切片）

### 布局
- [ ] minimap 左栏（每 atom 一 tick / >200 聚合成每 step 一格）
- [ ] 折叠 step 卡（信号头：actor + 摘要 + 工具足迹 chip）
- [ ] run group 可整体折叠（run 头：步数/工具数/error-recovery/loop）
- [ ] 展开 = typed-item 转录（A 层复用）

### 折叠策略（§12.5）
- [ ] user 总展开；assistant step 默认折叠
- [ ] pushback / analyzer-flag 的步自动展开

### 标注叠加（§12.6）
- [ ] turn/step chip 带 @version
- [ ] session header 显示 success/efficiency/safety
- [ ] 陈旧 badge（`v2 ready → 刷新？`）

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
- [ ] intent（8 类，LLM，USER_TURN）
- [ ] persona（4 类，LLM，USER_TURN）
- [ ] hard-interruption 检测（rule）
- [ ] error-recovery 检测（rule，STEP 级）

### 代码级信号（§1 可选 analyzer）
- [ ] §10.B.4 artifacts 表实装
- [ ] code-survival metric（行级人/机归因，需 commit 输入）
- [ ] committed lines 计数（效率分母）
- [ ] Semgrep pre/post 安全扫描

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
| Slice 2 标注 | 28 | 26 | **93%** |
| Slice 3 指标+浏览 | 10 | 0 | 0% |
| Slice 4 挑数据闭环 | 14 | 0 | 0% |
| 富 Viewer | 12 | 0 | 0% |
| Slice 5 铺广度 | 12 | 3 | 25% |
| 基础设施 | 12 | 8 | 67% |
| **合计** | **123** | **71** | **58%** |
