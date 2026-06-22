# traj-lens 设计文档

> **状态**：初稿 + 三方评审增量（§10）+ 单轨迹 viewer 设计（§12，2026-06-22）。
> **覆盖**：运行形态 · 中间格式（含 step/run 投影 §3.5）· 身份与版本 · 架构骨架 · 存储 schema · 标注中间件+LLM 客户端 · 选择/裁剪/导出 · 仓库结构与技术栈 · 评审采纳增量 · 可集成性 · 单轨迹 viewer（§12）。
> **日期**：2026-06-21（viewer 增补 2026-06-22）

---

## 0. 背景与目标

Claude Code / Codex / OpenCode 等 Coding Agent = **LLM + 脚手架**。我们要分析、观测这一过程中 LLM、脚手架、乃至用户行为的工作形态。

traj-lens 是 **Coding Agent 轨迹分析的底座平台**：对轨迹做可视化、基于规则/LLM 的标注与分析（轮次级 + 整体级），支持单条与批量处理，处理后可按指标排序/筛选/下钻，并支持「按训练价值裁剪轨迹用于数据回流（SFT/退火）」。

**强约束**：尽量复用既有、不引过重依赖、单仓库可管理量级；扩展性优先（功能可不断叠加）。

## 1. 验收基准（与 swe-chat 能力对齐）

设计阶段的验收标准：能完整承载 swe-chat（arXiv:2604.20779）所需的轨迹分析能力，并具更优扩展性。需能复现/承载的能力：

- **Session 级信号**：success 评分（0–100，LLM judge）、效率（token/cost/time per 100 committed lines）、安全（Semgrep 前后 diff）。
- **Turn 级信号**：user pushback（correction / rejection / failure_report / takeover）、prompt intent（8 类）、user persona（4 类）、hard-interruption 事件。
- **代码级信号**：行级人/机归因（确定性 replay → survived / agent-overwrite / human-overwrite / human-deletion）。*需额外的 commit 输入，列为可选 analyzer，不入 core。*
- **训练数据挖掘**：A 黄金 SFT（success≥90 且零 pushback）/ B 偏好对（pushback 前=rejected、纠正后被 commit=chosen）/ C 负样本（success<40 且 pushback≥2）；含 **continuation-session 完整性坑**（被纠正行为在上一 session → 必须过滤本 session 首个 agent 行为之前的 turn）。

> 现有原型 `swe-chat/analysis/glm_adapter.py` 已验证管线形态：`parse_transcript`(适配器) → `derive_signals`(规则/LLM 标注) → `classify`(A/B/C) → `viewer.html`(可视化)。traj-lens = 该原型的产品化 + 可扩展化。
> 训练导出目标 `panguml2.0` = OpenAI Chat Completions `messages` + `reasoning_content` + 逐轮 `weight`(loss mask) + `meta_info`。

## 2. 关键决策摘要

| # | 决策 | 取舍要点 |
|---|---|---|
| D1 | **运行形态 = 本地 Web 应用**：FastAPI + SQLite + React 单仓库 | 批量、LLM 标注任务、跨语料排序筛选天然要薄后端；SQLite 让排序/筛选快；仍轻量 |
| D2 | **中间格式 = Items-canonical**（Responses 风格扁平 typed item 流）；**两层**：raw 字节真相 + items 分析真相 | 分析单元=存储单元；标注/可视化/裁剪都简单；导出 panguml2 = 一次投影 |
| D3 | **身份 = 内容寻址**：`content_hash` 即 trajectory 身份；item 身份 = `(content_hash, index)` 作用域限轨迹内 | 重复样本自动认出并复用历史标注；只考虑「完全相同」；省全局 id |
| D4 | **标注/指标 = 内容寻址缓存 + 版本**：键 `(target_hash, annotator_id, version)`；version 自动派生于配置；多版本共存、手动刷新 | 去重/复用/版本/可复现一招到位；改 prompt/换模型自动分版本 |
| D5 | **扩展点收敛为四注册表**：adapters(in) / annotators / metrics / exporters(out) | 加能力 = 注册一个新函数（或一个 yaml），core 不动；in/out 对称 |

## 3. 中间格式：带出处的两层内容寻址模型

### 3.1 两层（各管各的权威，永不互相回写）

- **Raw 层 = 字节真相**（导出保真用）：原始 raw 逐字留存，按 `raw_sha` 取。
- **Items 层 = 分析真相**（标注/可视化/指标用）：从 raw 转出的干净工作副本。

> 「转换有没有损」的担忧被设计成走不到：分析按 items，导出按 raw 字节切片。

### 3.2 Item 模型（Responses 风格 typed item）

一条轨迹 = 一个扁平、有序、带类型的 item 列表。item 类型至少含：

| type | 语义 | 主要字段 |
|---|---|---|
| `message` | system/user/assistant/developer 文本 | `role`, `content` |
| `reasoning` | 思维链/慢思考 | `content` |
| `function_call` | 工具调用 | `name`, `arguments`, `call_id` |
| `function_call_output` | 工具结果 | `call_id`, `output` |

> 与训练形状的关系：导出时 `reasoning`+`function_call`+其后 `message` 投影回一条 assistant `message`（含 `reasoning_content`/`tool_calls`），`function_call_output` → `tool` 角色消息。

### 3.3 身份：内容寻址

```
content_hash = sha256( 规范化内容投影 )
   投影 = system + tools 定义 + 每条 message 的语义内容(role/text/reasoning/工具调用与结果)
   显式排除【易变 meta】：timestamp、token usage、脚手架 session id 等
```

- **trajectory 身份 = `content_hash`**（不是入库随机分配）。「完全相同」= content_hash 相同。
- **item 身份 = `(content_hash, index)`**，作用域限定在轨迹内 → 当且仅当整条轨迹完全相同时 item 才被认作同一个、标注才复用。这既安全（turn 标注依赖上下文，避免跨轨迹错误复用），又恰是「只考虑完全相同」的最简实现。

> ⚠️ 内容投影函数必须显式排除易变 meta，否则去重永远 miss。

### 3.4 出处指针（provenance）

每个 item 带指回原件原子的指针，供「按出处切片」导出：

```
it6 function_call Read(foo.py) call_id=c1
    provenance → { content_hash:T, origin:"messages[2].tool_calls[0]", raw_sha:... }
```

### 3.5 派生分组：step / run（确定性投影，不入存储）

items-canonical 扁平流之上可**确定性算出**两级分组，供 viewer（§12）与 STEP 级标注（§7.1）用；**不新存一层、不改正文**：

- **step** = agent loop 一次迭代 = `reasoning?` + 一或多个并行 `function_call` + 其 `function_call_output`；末尾 assistant `message` 收尾或自成末步。
- **run** = 一个 user 段之后连续的 assistant 自主段（含其全部 step）。单 prompt 蒸馏轨迹 = 1 user + 1 run（run 内常 50–80 step）。
- **phase**（explore / edit-test / finalize…）= 可选 rule 标注器产物，**不入 core**。

> 投影函数确定性 → 同一 `content_hash` 的分组稳定可复现；step 身份 = run 内序号，供 STEP 级标注挂载。**关键后果**：一条「单 user prompt → N 步自主」的蒸馏轨迹不会塌成「2 轮」，而是 1 user + N step（详见 §12.3）。

## 4. 标注与版本

### 4.1 标注 = 内容寻址的缓存条目

```jsonc
annotation {
  target_hash,        // = content_hash(整条) 或 (content_hash,index)(某 turn)
  annotator_id,       // "pushback" / "intent" / "success" ...
  annotator_version,  // = hash(规则代码版本 + 配置{prompt,model,参数})  ← 自动派生
  value,              // 标签/分数/结构
  inputs_hash, produced_at
}
缓存键 = (target_hash, annotator_id, annotator_version)
```

- **重复样本**：同 hash → 自动命中历史标注，不重跑。
- **配置变更**：version 自动变；旧标注原样保留，新版本在**主动**触发时才算（不自动刷新）→ 多版本共存。
- **多版本筛选**：annotation 带 version，可查 `pushback@v2` / `latest`；每 annotator 维护 `active_version` 指针供默认视图。

### 4.2 版本派生

`annotator_version` 由「规则代码版本 + 有效配置（prompt/schema/model/params）」哈希得到——改 prompt、换 model、改规则参数都自动产生新版本，无需人手 bump。

### 4.3 指标 provenance 与陈旧感知

metric 记录消费了哪些 `annotator@version`。UI 据此提示「此 success 基于 `pushback@v1`，现已有 `v2` → 刷新？」——**感知陈旧但等用户点**，不自动级联重算。

## 5. 架构骨架

### 5.1 数据流

```
多样输入(CC jsonl·Codex·panguml2/CC jsonl·自研…)
  └► ① Adapter 注册表  raw → Trajectory{raw_blob, items[], meta}（生成 content_hash / 出处指针）
        └► ② Items 存储 (SQLite + 磁盘 raw blob)
              ├► ③ 标注中间件 (rule|LLM) → annotations
              └► ④ 指标派生 → metrics
                    └► ⑤ 查询/排序/筛选 (SQLite, 跨语料)
                          ├► ⑥ Viewer/Web UI：列表→排序筛选→下钻→渲染 items+标注
                          └► ⑦ 选择/裁剪/导出：按谓词选子集/按原子切片 → 按 id 从 raw 导出 panguml2/偏好对
```

### 5.2 九模块

| # | 模块 | 职责 | 性质 |
|---|---|---|---|
| ① | `adapters/` | 每种输入一个：`raw→Trajectory` + 格式嗅探/注册表 | 确定性、无 LLM |
| ② | `core/` | Trajectory/Item 数据模型 + 出处 + 序列化（中间格式本体） | 小而稳 |
| ③ | `store/` | SQLite schema + 仓储；raw blob 存磁盘按 id 取 | 让排序/筛选快 |
| ④ | `annotate/` | 标注器接口 + 注册表 + 幂等并发 runner | 稳定/高效/可扩展 |
| ⑤ | `llm/` | 可靠 LLM 客户端：配置化、重试、限流、缓存、结构化输出 | 被 LLM 标注器复用 |
| ⑥ | `metrics/` | 从 items+标注派生 session/turn 聚合，喂排序 | 注册表式 |
| ⑦ | `export/` | 选择谓词 + 裁剪(原子边界+完整性) + 导出器 | 强制按 id 切原件 |
| ⑧ | `api/` | FastAPI 薄层：ingest/query/run-job/get/export，托管前端 | 薄 |
| ⑨ | `web/` | React+Tailwind 前端：列表筛选、轨迹 viewer、选择导出、配置面板 | 可视化主场 |

### 5.3 扩展点 = 四注册表（in/out 对称）

```
输入 adapters(in) ──► [ annotators · metrics ] ──► 导出 exporters(out)
```

加输入、加标注、加指标、加导出格式 = 注册一个新函数（LLM 标注器甚至只是一个 yaml），core 不变。

### 5.4 故意不做（保持不重）

- 不引消息队列/Celery：进程内 async 限流 runner + `jobs` 表记状态；单机瓶颈再换。
- 不上 Postgres/向量库：SQLite 扛 1e4–1e5 session 排序筛选足够。
- 不做鉴权/多租户：本地工具。
- 不搞 entrypoints 插件发现：注册表就是 dict，"插件"= import 时 `register()` 的模块。
- 代码存活/commit 归因：可选注册 metric，需额外 commit 输入，不入 core。

## 6. 存储 schema（SQLite + 磁盘 blob）

```
trajectories ( content_hash PK, items_count, created_at, meta )
ingestions   ( id PK, content_hash FK, source_path, raw_sha, ingested_at )   -- 多对一：一 content 多来源
raw_blobs    ( raw_sha PK → 磁盘路径 )                                        -- 导出保真
items        ( content_hash FK, index, type, payload, provenance )            -- 身份=(content_hash,index)
annotations  ( target_hash, annotator_id, version, value, inputs_hash, produced_at )  -- 内容寻址缓存
metrics      ( content_hash, metric_id, version, value, inputs[] )            -- 带 provenance
annotators   ( annotator_id, active_version, versions[]{version,config,note} )-- 版本台账
jobs         ( id, kind, target_set, annotator/metric, progress, errors, status )
```

## 7. 标注中间件 + 可靠 LLM 客户端

### 7.1 标注器接口（rule 与 LLM 共用壳）

```python
@dataclass
class AnnotatorSpec:
    id: str
    target: Target          # SESSION | USER_TURN | ASSISTANT_TURN | STEP | TOOL_RESULT ...
    context: ContextPolicy  # SELF | WINDOW(k) | PREFIX | WHOLE
    version: str            # = hash(code_ver + config)

class RuleAnnotator:  spec; def annotate(unit, ctx) -> Value          # 纯函数，确定性
class LLMAnnotator:   spec; prompt_template; response_schema; profile  # 声明式
                      def build(unit, ctx) -> messages
                      def parse(resp) -> Value
```

runner 按 `target` 枚举单元、按 `context` 投影上下文，再调 `annotate`（rule）或 `build→client→parse`（LLM）。runner 不关心类型。

> LLM 标注器拆成 build/schema/parse（调用交给共享 client）：① 重试/缓存/限流收口；② build/parse 不联网可单测；③ 新增 LLM 标注维度 = 纯配置（prompt+schema 文件），无需写 Python。

### 7.2 配置面（用户实际调的）

```
config/
  llm_profiles.yaml      # {name, base_url, key:${ENV}, model, temperature, max_tokens, timeout}
  annotators/
    pushback.yaml        # type:llm target:USER_TURN context:WINDOW(1) prompt_template/schema/profile
    intent.yaml          # type:llm target:USER_TURN ...
    success.yaml         # type:llm target:SESSION context:WHOLE inputs:[pushback@active]
    loop_detect.yaml     # type:rule params:{repeat>=3}
```

- 改 prompt/model/规则参数 → 文件变 → version 自动变 → 主动跑产生新版本。
- 密钥用 `${ENV}` 引用，不落盘。
- 切 base_url/key/model = 改 `llm_profiles.yaml` 或给标注器单独指 profile。

### 7.3 Runner：幂等 / 并发 / 可恢复 / 失败隔离

```python
async def run(corpus, annotator):
    work = [(t,u) for t in corpus for u in enumerate_targets(t, annotator.spec)]
    async with Semaphore(N):                       # 并发上限
        for (t,u) in work:
            key = (target_hash(t,u), annotator.id, annotator.spec.version)
            if store.has(key): continue            # 幂等 → 天然可恢复
            try:    store.put(key, compute(annotator,t,u))
            except FatalError as e: store.mark_error(key, e)  # 失败隔离
    jobs.update(progress, errors)
```

### 7.4 LLM 客户端（可靠性收口）

| 关注点 | 做法 |
|---|---|
| 配置 | profile 化（env+文件+标注器覆写），可多档（bulk 便宜模型 / 硬标签强模型） |
| 重试 | 指数退避，仅瞬时错(429/5xx/超时)，读 Retry-After；4xx 快速失败 |
| 限流 | 全局信号量 + 可选每档 token/QPS 桶 |
| 结构化输出 | 强制 schema：优先 provider structured-output/tool 模式，否则解析+校验 + 一次有界 repair；仍不合规则明确失败 |
| 可观测 | 每次记 tokens/延迟/成本，按 job 聚合 |
| 稳定性 | 默认 temperature=0；同请求命中标注缓存不重算；"重测"开新 run id |
| provider | 只认 OpenAI 兼容（base_url+key+model）：GLM/vLLM/多数厂商通用 |

### 7.5 故意不做

- 不做工作流 DAG 引擎：少数依赖用显式 `inputs:` 声明 + 一趟拓扑排序。
- 不建 provider 适配器动物园：只认 OpenAI 兼容。
- 不叠第二层缓存：标注级内容寻址缓存已够；观测到重复请求再加。
- prompt/schema 一律文件，不硬编码。

## 8. 选择 / 裁剪 / 导出

> **粒度区分**：可视化/标注按 item（细）；裁剪/导出按**原子**（粗）。原子 = items 按出处指针聚合的一组（同一 origin 的 items = 一个原子）。
> - 输入本是 message 形（panguml2/CC-jsonl）：原子 = 原始 message，可**字节保真**导出（切点落在原子边界）。
> - 输入是 raw agent 日志（无原始 message）：原子 = 投影出的逻辑步组，导出走**转换模式**（§8.5），非字节保真。

### 8.1 选择（语料级筛选 → 可复现集合）

```jsonc
Selection {
  predicate,                  // 对 metrics+annotations 的结构化过滤，如 success>=90 AND pushback_count==0
  pinned_versions,            // 引用到的 success@v2 / pushback@v3 ... ← 钉死版本=可复现
  members: [content_hash...],
  created_at
}
```

- A 类 = `success≥90 ∧ pushback_count==0 ∧ agent_lines>0`；C 类 = `success<40 ∧ pushback_count≥2`。一条 SQLite 查询。
- 钉版本 → Selection 可重放；版本变了重跑得新 Selection，旧的保留。

### 8.2 裁剪：四条合法性校验（`validate_trim` 强制）

一次 trim = 一段连续**原子** `[a,b]`，须全过：

| 校验 | 规则 | 防的是 |
|---|---|---|
| R1 边界对齐 | 切点落在原子边界 | 切坏原件 / 无法字节保真 |
| R2 工具配对闭合 | 范围内 `function_call`↔`function_call_output` 成对，无悬空 `call_id` | 残缺工具对 |
| R3 上文完整 | 起点 `a=0`（前缀，上文空）**或**保留 system+tools 框架且窗口自足；**默认仅前缀裁剪** | "起点上文为空或完整"；continuation 坑 |
| R4 结尾可训 | 结尾停在已解析的 assistant 轮（工具循环闭合） | 训练目标残缺 |

`validate_trim(traj,a,b) -> Ok | Reason`：非法即拒并给原因；配断言式自检。默认**前缀裁剪**覆盖 SFT 主场景，中段/前段窗口属进阶（须额外过 R3 自足校验，默认不开）。

### 8.3 mask vs trim（两条都不改正文）

- **mask**：保留整条（上下文天然完整），低价值 assistant 原子 `weight=0` → 只训高价值轮。**mask 决策记在 trim/export spec 里，导出时才写入产物的 `weight` 字段；canonical item 不动**（守住"两层不互写、不改正文"）。
- **trim**：前缀裁剪缩短长度。
- 可叠加：先裁前缀，再内部 mask。

### 8.4 偏好对（B 类），按 id 切原件

```
shared_prefix = [0..u]              # 到被纠正请求；两支共享上下文（按 id 切原件）
rejected      = u 之前那个 assistant 周期
chosen        = u 之后被接受(不再 pushback 且进 commit)的 assistant 响应
meta.correction_text = 用户纠正原文
```

**必过 continuation 过滤**：`u.turn_number > 本 session 首个 agent 行为` 才取（否则 rejected 在上一 session，跳过；报告量化为 8.7%）。rejected/chosen 均按 id 字节切原件、共享前缀。

### 8.5 导出器 = 第四注册表 · 两种保真模式

- **选择导出**（输入本是训练原件）：按 id 切原件 → **字节保真**。
- **转换导出**（输入是 raw 日志、无训练原件）：items→目标格式投影，标注「已转换，非逐字」。
- exporter 注册即用：panguml2 SFT jsonl / 偏好对 jsonl / sharegpt / 原样透传 …

### 8.6 导出产物可追溯（训练数据血缘）

```jsonc
ExportArtifact { selection, trim_spec, exporter_id+version, pinned_versions, created_at }
```

并把 provenance 顺手写进 panguml2 `meta_info`（teacher/query_source/owner…）→ 任何训练集都能回答"从哪个口径、哪个版本、怎么裁出来的"。

### 8.7 故意不做

- 不造通用查询 DSL：predicate 先用结构化过滤，不够再加表达式。
- 不用 ML 自动造偏好对：照搬确定性配方 + continuation 守卫。
- 不先做自动裁剪启发式：先人工点结尾原子+系统校验；"建议最高价值前缀"以后做成 metric 驱动助手。

## 9. 仓库结构与技术栈定版

### 9.1 仓库结构（单仓库：Python 后端 + web 前端）

```
traj-lens/
├─ pyproject.toml                # 一个 Python 包，依赖锁定
├─ config/
│  ├─ llm_profiles.yaml
│  └─ annotators/*.yaml          # 加 LLM 标注维度 = 丢一个 yaml
├─ src/trajlens/
│  ├─ core/      model.py · identity.py(内容投影+sha256) · registry.py(通用注册表)
│  ├─ adapters/  claude_code.py · codex.py · panguml2.py · openai_*.py · __init__(注册+嗅探)   ← in 注册表
│  ├─ store/     db.py(sqlite schema) · repo.py(轨迹/items/标注/指标/jobs/blob CRUD)
│  ├─ annotate/  base.py(Spec/协议/ContextPolicy) · runner.py(幂等并发) · loader.py(读 yaml) · rules/*.py
│  ├─ llm/       client.py(OpenAI 兼容: 重试/限流/缓存/结构化输出)
│  ├─ metrics/   base.py · builtin.py(success/计数/效率…)                                       ← 注册表
│  ├─ export/    select.py(Selection) · trim.py(validate_trim+原子聚合) · exporters/*.py        ← out 注册表
│  ├─ api/       app.py(FastAPI, 挂路由+托管前端) · routes/*.py
│  └─ cli.py     # typer: ingest/annotate/export/serve —— 与 API 调同一批底层函数
├─ web/          Vite+React+TS：pages(List/TrajectoryView/Config) · components(item 渲染/筛选)
└─ tests/        test_identity / test_trim / test_adapters + fixtures
```

> **CLI 与 API 调同一批底层函数**（都是薄壳）：批量=跑 CLI（headless/CI/cron），交互=开 web，两条路零重复逻辑。

### 9.2 技术栈定版（能不造就不造）

| 层 | 选 | 为什么 / 不用什么 |
|---|---|---|
| 语言 | Python 3.12+ + TypeScript | 数据/训练在 Python；前端 TS |
| 环境/依赖 | **uv** + 提交 `uv.lock`；部署 `uv sync --frozen` | 锁定精确版本→多处部署确定一致、杜绝"漏依赖"成本；`.python-version`+`requires-python` 锁 Python；uv 比 pip 快，迭代成本低。前端 `web/` 独立 npm lockfile |
| 模型/校验/Schema | **Pydantic v2** | 一处工具同做：Item 判别联合模型、config 校验、**LLM 结构化输出 schema** |
| API | **FastAPI + uvicorn** | 薄后端标配 |
| 存储 | **stdlib `sqlite3`** + 仓储函数 | 不上 ORM；真抖动再加 SQLModel |
| LLM 客户端 | **官方 `openai` SDK** 指向 base_url | 自带 base_url+重试+结构化输出，GLM/vLLM 通用；**不手搓 httpx**，只薄包加缓存/限流/profile |
| 重试/限流 | SDK 内置 + `asyncio.Semaphore` | 不引 Celery/队列 |
| CLI | **typer** | — |
| 配置 | **PyYAML** + Pydantic 校验 | 密钥 `${ENV}` 引用 |
| 前端 | **Vite + React + Tailwind** | — |
| 语料列表 | **TanStack Table + Query** | 排序/筛选/分页本职，轻且稳 |
| 图表 | **d3 仅时间线/热力图** | 其余 item 渲染=普通 React 组件 |
| 状态 | TanStack Query + `useState` | 不上 Redux |
| 运行 | `pip install -e .` → `trajlens serve`（FastAPI 同时供 API + 托管打包 web） | 单可部署物；dev vite proxy |

### 9.3 一条请求怎么流

```
ingest:   CLI/API → adapter(嗅探) → Trajectory(content_hash/items/provenance) → store(按 hash 去重·新 ingestion·raw blob)
annotate: API 建 job → runner 跑 selection×annotator → llm client(LLM 类) → annotations 缓存
browse:   web → query API → SQLite join metrics+annotations(active 版本) → TanStack Table
export:   web/CLI → Selection + trim → exporter → 文件(按 id 切原件)
```

### 9.4 实施切片（每片端到端可跑）

1. **走通骨架**：core 模型(含 §3.5 step 投影) + content_hash + Claude Code adapter + sqlite store(**开 WAL + `PRAGMA user_version` 迁移 runner**，§10.C.8/9) + 最小 API(ingest/get) + 最小 web(线性转录渲染 = §12.2 A 层)；暂无标注。
2. **标注中间件**：runner + llm client + 1 规则标注器 + 1 LLM 标注器(pushback) + yaml 配置 + job + viewer 显示标注。
3. **指标 + 浏览**：metrics + 列表排序/筛选。
4. **挑数据闭环**：Selection + `validate_trim` + panguml2 导出器 + 偏好对导出器。
5. **铺广度**：更多 adapter/标注器、代码存活 metric（可选 analyzer）。

> **富 viewer（§12 B+C hybrid）自成切片**，排在切片 2（已有标注数据）之后：折叠策略 / 信号叠加 / 陈旧 badge 都需要真实标注才好设计与验证；切片 1 的 web 只打通线性渲染。

### 9.5 运行与保活（OS 级成熟方案，不自造）

| 场景 | 方案 |
|---|---|
| 开发 | `trajlens serve`（uvicorn `--reload`） |
| 本地常驻（macOS） | **launchd** LaunchAgent：`RunAtLoad`+`KeepAlive` → 登录自启、崩溃自重启；plist 放 `deploy/` |
| 服务器（Linux） | **systemd** unit：`Restart=always` |
| 跨平台统一（可选） | supervisord，仅需要时引 |

- 单 uvicorn 进程 + asyncio（标注 runner 进程内并发）；**SQLite 开 WAL**（并发读 + 串行写）；**不开多 worker**（SQLite+多进程=争用）。
- `/api/health` 健康端点（对接本机 my-toolbox 门户 `/api/health` 约定）；保活靠 OS supervisor 在进程死亡时重启，健康端点供监控观测。
- "进程活着但不健康才主动重启"属过度设计，先不做。

### 9.6 故意不做

不上 monorepo 工具 / 不先写 Dockerfile / 不上 ORM / 不手搓 HTTP 客户端 / 不上 Redux / 不自造守护进程。

## 10. 评审采纳的增量（三方评审 2026-06-22）

三个 reviewer（架构可扩展性 / 技术栈与运维 / swe-chat 验收与数据模型）一致认可脊椎（两层内容寻址+出处、四注册表、栈选型）抗重写、是"正确的懒"；共识缺口为「注册表登记节点、但能力叠加会长出未被管理的『边』与『旁路数据』」。以下增量已采纳，按"对应章节"理解为对前文的修订。

### 10.A 正确性（不补会悄悄污染训练数据）

1. **R3 续接守卫**（修订 §8.2）：`a=0` 不等于上文完整。续接 session（首个 user turn 在任何 agent 行为之前、且引用上一 session 状态）若按前缀从 `a=0` 导出，会产出开头引用缺失上下文的"假黄金"样本，**A 类也中招**（不止 B 类）。R3 增加断言：除 `a=0`/窗口自足外，还须「非续接，或 turn0 自足」。续接性作为一个信号（来源 meta 或一个 continuation 检测标注器）；未知时保守告警、交用户判。
2. **commit 派生标注按 `raw_sha`/ingestion 键，而非 `content_hash`**（修订 §3.3/§4.1）：content_hash 故意排除 commit 状态，故两条字节相同但 commit 结果不同的对话会塌缩为同一身份。凡 commit/artifact 派生的标注与指标，键用 `ingestion.id`（`raw_sha`），不用 content_hash。对话型标注仍用 content_hash。
3. **`committed` 升为一等可选指标 + 谓词缺失即响亮失败**（修订 §8.1/§8.4）：B 类 `chosen∈commit` 与效率分母都依赖 `committed`；缺失时**不得静默降级/置 0**，要么报缺、要么显式声明降级口径（如 chosen 退化为"此后无 pushback"并标注质量下降）。

### 10.B 上限（现在零成本预留，免日后改模型）

4. **预留 `artifacts` 旁表**（修订 §6）：
   ```
   artifacts ( raw_sha FK, kind={diff,commit,snapshot}, payload )   -- 可空；commit/代码基质
   ```
   标注器/指标声明 `needs_artifacts`。code-survival、效率分母（committed lines）、Semgrep、B-chosen 四能力共用此基质——现在建张可空表即可，日后接入不动 core。
5. **依赖升为一等声明**（修订 §5.3/§7.5）：注册表登记"节点"，但 `inputs:[pushback@active]` 是"边"。把依赖收进每个 spec 的 `depends_on`，集中校验 + 一趟拓扑排序（引擎仍极简）；依赖图集中拥有，不散落 yaml。
6. **版本覆盖率可查询**（修订 §4）：`active_version` 是单一全局指针，表达不了"语料一半 v1 一半 v2"。提供 per-(语料, annotator) 覆盖率查询（"k% 在 v2"），筛选/刷新基于覆盖事实而非假设全量同版。
7. **规则标注器版本用 `logic_version` 常量 + config 哈希**（修订 §4.2）：避免"改空格/重构就 orphan 整个缓存"。全代码哈希只留给 LLM spec（其 config 即逻辑）。

### 10.C 实现期小代码（非架构改动，记下别忘）

8. **SQLite 单写者纪律**（实现于 §6/store）：WAL = 并发读 + **单写**；async N 写者会 `SQLITE_BUSY`。所有写经**一个专用 writer 连接/任务**串行化，semaphore 只扇出 LLM 调用；`busy_timeout=5000`、`synchronous=NORMAL`、写事务 `BEGIN IMMEDIATE`。~15 行，**必须有**，否则 runner 批量不可用。
9. **极简迁移**（实现于 §9）：`PRAGMA user_version` + `migrations/NNN_*.sql` 跑批器（~30 行）；不引 Alembic（无 ORM 太重）。
10. **单一重试归属**（实现于 §7.4）：openai SDK 自带 `max_retries` 会与我方 semaphore/退避叠加且吞掉 rate-limit 头。择一：保留 SDK 重试，则包装层不再重试瞬时 429/5xx；semaphore 按"请求延迟"而非 RPM 保守取值。

### 10.D 评审确认保持不动

两层内容寻址 + 出处（抗重写脊椎）· uv+lock · 官方 openai SDK · launchd/systemd · 不上 ORM/Celery/Redux · 8 个对话型信号 fit cleanly · mask/trim（R1/R2/R4 + 两层不互写）正确。

## 11. 可集成性（被第三方系统集成）

**设计立场：API-first，headless 可用；自带 web 只是参考客户端。** 第三方与我们的 web 走同一套 API → 契约一致、自动 dogfood。地基已在：API-first + content_hash 幂等 + items-canonical 干净 JSON。

### 11.1 三种集成面（同一 core 之上的薄壳）

- **HTTP 服务（主）**：REST + FastAPI 自动 OpenAPI → 第三方拿带类型契约、可代码生成客户端、Swagger 文档；版本化 `/api/v1`。
- **库内嵌（免费）**：第三方若是 Python，`import trajlens` 直接调 core，省网络跳（CLI/API/库共用 core）。
- **MCP（后置/廉价）**：日后给 AI-agent 平台加一层 MCP 壳，不动核心。先不做。

### 11.2 集成端点（全建在已有能力上）

| 诉求 | 端点 |
|---|---|
| 传入单条/多条 | `POST /api/v1/trajectories`（inline 批量；按 content_hash **幂等**返回 id+已有标注） |
| 触发标注任务 | `POST /api/v1/jobs`（一组 id × annotator；idempotency-key 防重复建任务） |
| 查看进展 | `GET /api/v1/jobs/{id}`（status/进度/错误）+ **可选 webhook**（建任务给 `callback_url`，完成 HMAC 签名回调）；轮询为基线 |
| 拿结果 / 筛选回传 | `GET /trajectories?filter=` → id+摘要；`GET /trajectories/{id}` → items+标注+指标全量（供自建可视化）；`POST /exports`（selection+trim+exporter）→ 导出产物（下载链/inline jsonl） |
| 读标注元数据 | `GET /catalog/{annotators\|metrics\|exporters}` → 每项 id、target、**value schema**、active_version、版本表 |

### 11.3 契约与边界

- **DTO = pydantic 模型**（trajectory/item/annotation/metric）→ 同喂 OpenAPI 契约与我们 web，单一来源。
- **集成 ≠ 扩展**：第三方**用** API（提交/触发/拉取/读元数据），不上传代码；新增 annotator/metric/exporter 仍在本仓库注册。扩展在内、集成在外。
- **鉴权（修订 §5.4「不做鉴权」）**：API-key **可选**——本地独立用可关（或仅 localhost）；集成时开静态 token/少量 key（config）。不做 OAuth/多租户/计费，后置。

### 11.4 故意不做

不做 GraphQL（REST+OpenAPI 够）/ 不做多租户 SaaS / 不做第三方远程注入标注器（集成靠调 API，不靠传代码）/ webhook 只做最小签名推送，复杂事件总线后置。

## 12. 可视化：单轨迹 viewer（B+C hybrid · 2026-06-22 增补）

> 回应两件事：①「可视化效果非常重要」；②「单 user prompt → 50–80 步 assistant 自主 run」这一**主力训练数据形态**（教师蒸馏，中途无 user 介入）。本节定 viewer 设计，并对 §3/§7.1/§9.4 作小修订（§12.9）。设计草图见 `mockups/viewer-*.html`。

### 12.1 三个工作面（同一 API 之上的薄壳）

- **语料列表**（settled）：TanStack Table，按 metrics/annotations 排序/筛选/分页 → 点进单轨迹。
- **单轨迹 viewer**（本节重点）：B+C hybrid。
- **选择/裁剪/导出**：在 viewer 内完成（左缘勾选 + 底部 R1–R4 实时校验），呼应 §8。

### 12.2 核心隐喻：三层缩放 = 数据三层高度

progressive disclosure，每层正好对应 §3 数据模型的一层 → UI 即在教用户 schema：

| 缩放层 | UI 元素 | 数据高度 |
|---|---|---|
| 全局形状 | 左侧 **minimap**（每 atom 一 tick，按类型着色） | atom |
| 节奏 | 折叠的 **信号头卡片** | step / turn |
| 正文 | 卡片展开 = **typed-item 转录** | item |

三者复合、不互相取代：线性转录（方向 A）活在展开的卡内、minimap（方向 B）是左栏、信号头卡（方向 C）是右栏。

### 12.3 卡片单元 = step（不是会话轮）★

承 §3.5：user 段 → 1 张 user 卡；assistant 自主段 → 1 个可整体折叠的 **run group**，内含 N 张 **step 卡**。

- **长 run（单 prompt 蒸馏）= 1 user 卡 + N step 卡，不塌成「2 卡」**。run 组头给 run 级聚合（步数 / 工具数 / error-recovery / loop 计数）。
- assistant 永不被压成单条缩略：run 头给摘要、逐 step 卡给节奏、展开给逐字 item。

### 12.4 minimap = 全局形状

每 atom 一 tick，按类型着色；pushback / hard-interruption / error-recovery / loop 打旗；蓝框 = 当前视窗，点击跳转。`atom 数 > ~200` 时**聚合成每 step 一格**（色 = 主类型，含 pushback/中断则打旗），避免退化成 1px 噪声。长自主 run 的「真实长带」正是此设备的用武之地。

### 12.5 折叠策略 & 头部信号（默认值）

- user 轮**总展开**（本就一条短 item）；assistant step **默认折叠**；**被 pushback 命中、或被 analyzer flag（error-loop 等）的步自动展开**——失败不藏。
- 折叠头露：actor + 一行摘要 + 工具足迹 chips + 该单元自身信号 chips（user 露 intent；有 pushback 露 pushback）。
- session 级信号（success/efficiency/safety）只在顶部 header，不逐卡重复；run 级聚合只在 run 组头。

### 12.6 标注 / 版本 / 陈旧叠加

turn/step 信号 = 卡上 chips（带 `@version`）；session 信号 = header；陈旧感知 badge「success 基于 `pushback@v1`，`v2` ready」——**感知陈旧但等用户点**，不自动级联重算（呼应 §4.3）。

### 12.7 trim / mask 交互（呼应 §8）

- 左缘勾选 = 选一段连续 **atom** 区间；底部条**实时跑 R1–R4**，非法亮红并给因（如续接守卫 R3）。
- per-atom / per-step **mask weight=0**：导出时才写入产物、**不改 canonical**（守 §8.3 两层不互写）。
- 蒸馏长 run 的主操作 = mask 低价值步（如 loop 段）；前缀天然完整（上文 = 单条 user prompt），少需 trim。

### 12.8 技术（呼应 §9.2，不加重依赖）

item 渲染 = 普通 React 组件；minimap = 纯 CSS / 轻量 d3；列表 = TanStack Table；step 数大时用 `react-window` 虚拟化长列表。

> **分组的单一来源**：step/run 投影在 `core/`（Python，§3.5）一处算，经 trajectory DTO（每 item 带 `step_id`/`run_id`）下发；前端**只渲染**、不重算——既喂 STEP 级标注（§7.1 后端枚举单元）又喂 viewer，避免 Python/TS 两份实现漂移（呼应 §11.3 单一 DTO 来源）。phase 分组同理来自后端 rule 标注器。

### 12.9 对前文的修订

1. **§3 新增 §3.5**：step/run 为对扁平 item 流的确定性投影，**不入存储**（items-canonical 仍是唯一真相）。
2. **§7.1**：annotator `target` 增加 **`STEP`** → `SESSION | USER_TURN | ASSISTANT_TURN | STEP | TOOL_RESULT`。
3. **§9.4 slice 1**：store 即开 SQLite WAL + `PRAGMA user_version` 迁移 runner（§10.C.8 单写者纪律等 slice 2 异步 runner 再上）；最小 web 只做线性转录（§12.2 A 层）。
4. **富 viewer（本节）自成切片**，排在 slice 2 之后（需真实标注数据才好设计验证）。
5. **phase 分组**（explore/edit-test/finalize）= 可选 rule 标注器，不入 core。

### 12.10 故意不做

不做像素级定制图表库 / 不做实时协作多人光标 / minimap 不做可缩放时间轴（聚合够用）/ 不在 canonical 存任何分组（全是投影，渲染时算）。
