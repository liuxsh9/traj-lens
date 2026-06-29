# 轨迹语义检索设计(trajectory search)

> 标注完成后,用自然语言搜索想要的轨迹用于训练数据筛选。
> 不是简单关键词匹配:结合词法、向量与轨迹结构特性的混合检索。

## 1. 背景与目标

标注 / 指标计算完成后,需要从大量轨迹中筛选满足条件的样本组成训练集。典型 query:

- "使用了读 csv 的数据" → 命中含 `read.csv` / `pd.read_csv` 等调用的轨迹(如样本 `4615249f`)。
- "写了测试的代码" → 命中产生测试代码改动的轨迹。
- "发现 xxx 问题并完成了修复" → 组合条件(问题 + 修复)。

这些 query 表面都是"语义搜索",实则分三层:**词法/符号精确匹配**(例 1)、**已计算的结构化事实**(例 2)、**组合谓词**(例 3)。设计据此分层,而非一律走向量 RAG。

## 2. 范围

- **v1 聚焦场景 1**:人工在 UI 输入 query → 看结果 + 命中证据 → 筛选样本。容忍模糊召回,重排可接受。
- **向前兼容场景 2**:自动数据管线(数据回流 / 训练过滤),要求 query 可复现、可审计、可版本化。
- 兼容手段:**稳定 DSL 作为中间层**。场景 1 走 LLM 自然语言入口翻译成 DSL;场景 2 直接提交 DSL,绕过 LLM。

## 3. 关键决策(已锁定)

| 决策点 | 选择 |
|---|---|
| NL → 查询 | LLM 翻译成稳定 DSL(可展示、可编辑、可复现) |
| 召回引擎 | FTS5(BM25)+ sqlite-vec(向量 ANN)双路 + facet 过滤,RRF 融合 |
| 检索粒度 | 双粒度:item 级(精确定位)+ step 级(语义完整) |
| embedding | 本地 **bge-m3**(1024 维),OpenAI 兼容 `/embeddings` 端点;dev/prod 同模型 |
| 返回单位 | 轨迹级(content_hash)+ 命中证据 |
| 新依赖 | 仅 `sqlite-vec` |

被淘汰的替代:纯词法+facet(满足不了语义诉求)、整轨迹单向量(needle 稀释)。

## 4. 总体架构(三层)

```
查询层   NL ──LLM翻译──▶ 稳定DSL(JSON) ──▶ 查询计划
                                    │ 场景2 直接提交此 JSON,绕过 LLM
召回层   facet过滤(SQL缩集) ──┬──▶ 符号/FTS5 BM25 排名 ──┐
                              └──▶ sqlite-vec KNN 排名 ───┴─▶ RRF融合 ─▶ 轨迹聚合+排序 ─▶ 结果+证据
索引层   ingest/标注后 ──异步job──▶ 逐chunk建 FTS5行+symbols+向量;backfill命令补存量
```

三层接口清晰:查询层只产 DSL;召回层只吃 DSL 吐排序;索引层只把 trajectory 变成可检索 chunk。

## 5. 数据模型(新增表)

```sql
-- 可检索 chunk(item 与 step 双粒度共表,granularity 区分)
CREATE TABLE search_chunks (
  chunk_id     TEXT PRIMARY KEY,        -- sha256(content_hash|granularity|idx)
  content_hash TEXT NOT NULL REFERENCES trajectories(content_hash),
  granularity  TEXT NOT NULL,           -- 'item' | 'step'
  idx          INTEGER NOT NULL,        -- item idx 或 step_id
  role         TEXT,                    -- message 的 role,可空
  item_type    TEXT,                    -- message/reasoning/function_call/function_call_output/step
  fn_name      TEXT,                    -- function_call 的 name,可空
  symbols      TEXT NOT NULL DEFAULT '',-- 抽取出的符号,空格分隔(见 §7)
  text         TEXT NOT NULL,           -- 可搜投影(见 §6)
  text_sha     TEXT NOT NULL,           -- 内容寻址缓存键(见 §10)
  output_ok    INTEGER                  -- call↔output 配对成败,1/0/NULL(见 §8)
);

-- FTS5 全文索引(symbols/fn_name 高权重,见 §9)
CREATE VIRTUAL TABLE search_fts USING fts5(
  symbols, fn_name, text,
  content='search_chunks', content_rowid='rowid'
);

-- 向量索引(bge-m3,1024 维;维度随模型,换模型重建)
CREATE VIRTUAL TABLE search_vec USING vec0(
  chunk_rowid INTEGER PRIMARY KEY,
  embedding FLOAT[1024]
);

-- embedding 缓存:text_sha + model_id 不变则复用,避免重复 embed
CREATE TABLE embed_cache (
  text_sha TEXT NOT NULL,
  model_id TEXT NOT NULL,
  embedding BLOB NOT NULL,
  PRIMARY KEY (text_sha, model_id)
);
```

facet(resolution / topic / pushback / has_tests / success_score / security…)**复用现有 `annotations` 与 `metrics` 表**,检索时 JOIN,不复制。

## 6. 可搜文本投影(per chunk)

| item 类型 | 投影内容 | 降噪 |
|---|---|---|
| message | content | `system` 角色默认排除(模板噪声),单列为 facet |
| reasoning | content | — |
| function_call | name + arguments(JSON 解析后取值) | 丢键名噪声;抽符号(§7) |
| function_call_output | output | **头尾截断**(§8),超长再按窗口切分 |
| step(双粒度) | 该 step 内 item 投影拼接 | grouping.py 投影 |

`role` / `item_type` / `fn_name` / `symbols` 留作结构列,支撑 field-scoped 查询("read csv 在工具调用里" vs "用户在问 csv")。

## 7. 符号抽取索引(symbol index)— 核心竞争力

轨迹里 `function_call.arguments` 和 bash 命令不是散文,语义集中在**符号**(函数名、库、命令、文件后缀)。向量会摊薄 `read.csv("a.csv")` 的语义,BM25 会被参数噪声干扰。

**做法**:投影时用轻正则抽出 callee 符号 / 命令首 token / 文件扩展,写入 `symbols` 列并作 FTS5 高权重字段。"用了 read.csv" → 精确命中符号,**比向量准、比向量便宜**。

抽取规则(正则,覆盖 ~80%):

- callee:`\b([\w.]+)\s*\(` → `read.csv`、`pd.read_csv`、`pytest.main`
- 命令首 token:bash/shell 调用取第一个词 → `pytest`、`git`、`npm`
- 文件扩展:`\.\w+\b` 中的常见数据/代码后缀 → `.csv`、`.py`、`.json`
- 库 import:`import (\w+)` / `from (\w+)` / `library\((\w+)\)`

升级路径:精度不够时换 tree-sitter AST(重依赖,v1 不做)。

## 8. call↔output 配对(动作-结果单元)

`call_id` 把 `function_call` 与其 `function_call_output` 绑成因果对。

- 索引时按 call_id 配对,给 function_call chunk 写 `output_ok`(output 是否含报错 / 非零退出的轻启发式)。
- 证据展示成"动作→结果"对,支撑"用了 X **且成功/失败**"这类组合 query,可信度更高。
- 工具输出**头尾截断**:`function_call_output` 信息集中在头(命令/调用)+ 尾(结果/报错),中段大段日志/dump 省略。防止信号稀释 + 省 bge-m3 token。

## 9. DSL 规范(稳定中间层)

JSON 形式,可序列化 / 版本化 / 审计。LLM 翻译产出它;UI 渲染成可编辑表单 + 原始 JSON 双视图;场景 2 直接提交。

```json
{
  "any": [
    {"text": "read.csv",   "scope": {"item_type": "function_call"}, "field": "symbols"},
    {"text": "pd.read_csv", "scope": {"item_type": "function_call"}, "field": "symbols"},
    {"text": "csv.reader"}, {"text": "fread"}
  ],
  "filters": {"resolution": "resolved", "has_tests": true}
}
```

- `any` / `all`:布尔组合;每项可带 `scope`(role/item_type 限定)与 `field`(symbols/text 定向)。
- `filters`:落到 facet(JOIN annotations/metrics)。
- `version`:DSL schema 版本号,保证场景 2 的查询长期可复现。

## 10. 检索执行 + RRF 融合

1. `filters` 先 SQL 缩集(JOIN annotations/metrics)——facet 最便宜,先砍。
2. **向量路短路**:若 DSL 纯符号 / facet 可判定(如"写了 pytest 的"),跳过向量召回,省查询 embedding + KNN。能精确匹配就不向量。
3. 缩集内并行:FTS5 BM25 排名(symbols/fn_name 列高权重)+ sqlite-vec KNN 排名。
4. **RRF**(`k=60`)按 rank 融合两路,解决两路分数不可比。
5. chunk 分数按 `content_hash` 聚合(取轨迹内最高分 chunk),输出**轨迹级**排序。
6. 每条结果附**命中证据**:item_idx、文本片段、命中符号/词、向量相似度、动作-结果对。

## 11. 索引构建 / 增量

- ingest / 标注后投递 **index job**(复用现有 `jobs` 表 + job queue),异步建 chunk + FTS5 + 向量。
- embedding 走 `llm_client` 的 `/embeddings`(复用 `LLM_RPS` 限流);bge-m3 本地服务。
- **内容寻址缓存**:`text_sha + model_id` 命中 `embed_cache` 则复用——幂等且省算力。
- `trajlens index --backfill` 回填存量;`model_id` 变更触发 staleness 重建(照搬 metrics 机制),sqlite-vec 表维度跟随模型。

## 12. 同义词扩展(词法路效果关键)

- LLM 翻译阶段为代码意图生成同义词组(`读 csv` → `read.csv / pd.read_csv / csv.reader / fread / read_csv`),作 FTS5 OR 查询。
- 维护一份静态种子词典(常见 IO / 测试 / 框架函数)兜底,降低对 LLM 的延迟与依赖。

## 13. embedding provider(本地 bge-m3)

- 模型:**bge-m3**(1024 维,中英 + 代码混合场景)。
- 接口:OpenAI 兼容 `/embeddings`,复用 `llm_client`,模型由 `.env` 配。
- **dev**:Ollama 跑 bge-m3 量化 GGUF(慢但向量空间与 prod 一致,召回行为可复现)。
- **prod**:text-embeddings-inference(TEI)多核 + 动态合批 + ONNX/int8,CPU 资源充足。
- 约束:**dev/prod 同模型同维度**,否则查询向量与库向量不可比;`model_id` 进缓存键与 staleness。

## 14. 错误处理(全程可降级,不阻塞)

| 故障 | 降级 |
|---|---|
| LLM 翻译失败/超时 | 退回纯关键词 FTS5(原文 tokenize)+ 提示可手动编辑 DSL |
| embedding 服务挂 | 向量路缺失,RRF 走单路(符号/FTS5+facet),UI 标注"语义召回暂不可用" |
| sqlite-vec 加载失败 | 同上降级,不阻塞启动 |
| 索引落后于数据 | 结果标注"N 条尚未索引" |

## 15. 测试

- **DSL**:NL→DSL 金标用例(标 `slow`,打 LLM)+ 纯解析/序列化单测(不联网)。
- **符号抽取**:断言 `read.csv("a.csv")` → 抽出 `read.csv`、`.csv`;`pytest tests/` → `pytest`。
- **召回正确性**:灌 `tests/samples`,断言"read csv" query 命中含 `read.csv` 的样本(`4615249f` 场景)。
- **RRF**:构造两路排名,断言融合顺序。
- **降级**:mock embedding 不可用,断言符号/FTS5-only 仍返回。
- **端到端 smoke**:`__main__` 跑一条 NL→DSL→检索→证据。

## 16. 明确不做(技术税 > 收益,留作升级路径)

- tree-sitter 全量 AST 解析 — 正则覆盖 ~80% 够。
- cross-encoder / learned reranker 重排 — RRF 先行,延迟与依赖都重。
- 把 resolution/score 混进 embedding 文本 — 污染向量空间,facet 已能过滤。
- 微调专用轨迹 embedding — bge-m3 够起步。
- 独立第三路"符号引擎" — 符号做成 FTS5 高权重字段即可。

## 17. 净增量小结

- 新表:`search_chunks` / `search_fts` / `search_vec` / `embed_cache`。
- 新代码:符号抽取正则、投影截断/配对、DSL 翻译+解析、RRF 融合、index job。
- 新依赖:仅 `sqlite-vec`。embedding / LLM 翻译复用 `llm_client`。
- facet 全部复用现有 `annotations` / `metrics`。
