# 轨迹检索内核(trajectory search core)Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建 DSL 驱动的混合检索后端内核——把轨迹切成 item/step chunk、抽符号、建 FTS5+向量索引,用 RRF 融合三路召回返回轨迹+命中证据,可用真实长轨迹端到端验证。

**Architecture:** 新增 `src/trajlens/search/` 模块,迁移 `012_search.sql` 建 chunk/FTS/向量/缓存表。索引层把 `Trajectory` 投影成 chunk(符号抽取 + 输出头尾截断 + call↔output 配对)并 embed;查询层吃稳定 DSL(JSON),先 facet 缩集(复用 `repo.query_matching_hashes`),再并行跑符号精确匹配 / FTS5 BM25 / sqlite-vec KNN,RRF 融合后按轨迹聚合。embedding 复用 `llm_client` 风格打 `/embeddings`(本地 bge-m3)。

**Tech Stack:** Python 3.12, SQLite(FTS5 内建 + `sqlite-vec` 扩展), Pydantic v2, httpx, typer, FastAPI, pytest。

**范围说明:** 本计划 = 后端检索内核 + CLI + 一个查询 API 路由(可用 DSL JSON 端到端验证,对应 spec 场景 2 路径)。**不含** NL→DSL 的 LLM 翻译、LLM 同义词扩展、搜索 UI —— 见末尾「后续计划」。这样内核可独立 TDD,并用真实长轨迹验证召回。

---

## File Structure

**新建:**
- `src/trajlens/search/__init__.py` — 模块导出
- `src/trajlens/search/symbols.py` — 符号抽取(正则)
- `src/trajlens/search/projection.py` — 可搜文本投影 + 输出头尾截断
- `src/trajlens/search/chunks.py` — Trajectory → item/step chunk(双粒度)+ call↔output 配对
- `src/trajlens/search/dsl.py` — DSL pydantic 模型 + 解析
- `src/trajlens/search/fusion.py` — RRF 融合(纯函数)
- `src/trajlens/search/embed.py` — `/embeddings` 异步客户端(复用 llm_client 风格)
- `src/trajlens/search/index.py` — 建索引(写 chunk/FTS/向量/缓存)
- `src/trajlens/search/query.py` — 执行检索(facet + 符号 + FTS + 向量 + RRF + 聚合 + 证据)
- `src/trajlens/store/migrations/012_search.sql` — 新表
- `tests/test_search_symbols.py` / `test_search_projection.py` / `test_search_chunks.py` / `test_search_dsl.py` / `test_search_fusion.py` / `test_search_index.py` / `test_search_query.py` / `test_search_e2e.py`

**修改:**
- `src/trajlens/store/db.py:7-16` — `connect()` 加 sqlite-vec 扩展加载(优雅降级)
- `src/trajlens/cli.py` — 新增 `index` 命令
- `src/trajlens/api/routes.py` — 新增 `POST /api/v1/search` 路由

**设计边界:** 每个 search 子模块单一职责;`index.py` 与 `query.py` 都只依赖 `chunks`/`dsl`/`fusion`/`embed` 的纯接口,便于注入 fake embedder 做单测(不打网络)。

---

## Task 1: worktree + 隔离环境 + sqlite-vec

**Files:**
- Modify: `src/trajlens/store/db.py:7-16`
- Create: `tests/test_search_vec_ext.py`

- [ ] **Step 1: 创建 worktree 并装依赖**

```bash
make worktree NAME=search-core      # 创建 ../tl-search-core,分支 feat/search-core
cd ../tl-search-core
uv add sqlite-vec                    # 新依赖,写入 pyproject
uv sync
```

- [ ] **Step 2: 配置独立测试服务端口(不碰主 :8000)**

```bash
cat > .env.search <<'EOF'
TRAJLENS_DB=trajlens_search.db
TRAJLENS_BLOBS=blobs_search
TRAJLENS_PORT=8011
TRAJLENS_HOST=127.0.0.1
EOF
```

手动验证服务时用:`env $(cat .env.search | xargs) uv run trajlens serve --no-build`(端口 8011,独立 db,不影响主 checkout 的 :8000)。

- [ ] **Step 3: 写失败测试 —— connect 后能加载 vec0**

`tests/test_search_vec_ext.py`:

```python
import sqlite3
import pytest
from trajlens.store import db as dbmod


def test_vec_extension_loads(tmp_path):
    conn = dbmod.connect(str(tmp_path / "t.db"))
    # vec0 virtual table only creatable if the extension loaded
    conn.execute("CREATE VIRTUAL TABLE v USING vec0(rowid INTEGER PRIMARY KEY, e FLOAT[4])")
    conn.execute("INSERT INTO v(rowid, e) VALUES (1, '[1,2,3,4]')")
    rows = conn.execute(
        "SELECT rowid FROM v WHERE e MATCH '[1,2,3,4]' ORDER BY distance LIMIT 1"
    ).fetchall()
    assert rows[0]["rowid"] == 1


def test_connect_degrades_without_vec(monkeypatch, tmp_path):
    # if sqlite_vec import fails, connect() must still return a usable conn
    monkeypatch.setattr(dbmod, "_load_vec", lambda conn: False)
    conn = dbmod.connect(str(tmp_path / "t.db"))
    assert conn.execute("SELECT 1").fetchone()[0] == 1
```

- [ ] **Step 4: 运行,确认失败**

Run: `uv run pytest tests/test_search_vec_ext.py -x -q`
Expected: FAIL（`no such module: vec0` 或 `_load_vec` 不存在）

- [ ] **Step 5: 实现 db.py 扩展加载（优雅降级）**

`src/trajlens/store/db.py` 替换 `connect`,新增 `_load_vec`:

```python
import logging
log = logging.getLogger("trajlens.db")


def _load_vec(conn: sqlite3.Connection) -> bool:
    """Load the sqlite-vec extension. Returns False (and logs) if unavailable so
    search degrades to FTS+symbol instead of crashing the whole app."""
    try:
        import sqlite_vec
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        return True
    except Exception as e:  # extension missing / load blocked
        log.warning("sqlite-vec unavailable, vector search disabled: %s", e)
        return False


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.vec_ok = _load_vec(conn)   # attribute callers can check
    return conn
```

- [ ] **Step 6: 运行,确认通过 + 全量回归**

Run: `uv run pytest tests/test_search_vec_ext.py -x -q && uv run pytest -q`
Expected: PASS（新测试 2 条通过,旧测试不回归）

- [ ] **Step 7: Commit**

```bash
git add -p src/trajlens/store/db.py tests/test_search_vec_ext.py pyproject.toml uv.lock
git commit -m "feat: load sqlite-vec extension with graceful degradation"
```

---

## Task 2: 迁移 012_search.sql

**Files:**
- Create: `src/trajlens/store/migrations/012_search.sql`
- Create: `tests/test_search_index.py`(本 task 只放 schema 测试,后续 task 复用此文件)

- [ ] **Step 1: 写失败测试 —— 迁移建出四张表**

`tests/test_search_index.py`:

```python
from trajlens.store import db as dbmod


def test_migration_creates_search_tables(tmp_path):
    conn = dbmod.connect(str(tmp_path / "t.db"))
    dbmod.migrate(conn)
    names = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view')").fetchall()}
    assert {"search_chunks", "embed_cache"} <= names
    # FTS5 + vec0 are virtual tables
    vt = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "search_fts" in vt
    assert "search_vec" in vt
```

- [ ] **Step 2: 运行,确认失败**

Run: `uv run pytest tests/test_search_index.py::test_migration_creates_search_tables -x -q`
Expected: FAIL（表不存在）

- [ ] **Step 3: 写迁移**

`src/trajlens/store/migrations/012_search.sql`:

```sql
-- Trajectory search index (design 2026-06-29). Chunks are a derived projection
-- of items (item + step granularity); FTS5 indexes natural-language text only,
-- symbols matched exactly via the symbols column, vectors in sqlite-vec.
CREATE TABLE IF NOT EXISTS search_chunks (
  id           INTEGER PRIMARY KEY,            -- maps to search_vec rowid
  chunk_id     TEXT NOT NULL UNIQUE,           -- sha256(content_hash|gran|idx)
  content_hash TEXT NOT NULL,
  granularity  TEXT NOT NULL,                  -- 'item' | 'step'
  idx          INTEGER NOT NULL,
  role         TEXT,
  item_type    TEXT,
  fn_name      TEXT,
  symbols      TEXT NOT NULL DEFAULT '',       -- space-delimited, space-padded
  text         TEXT NOT NULL,
  text_sha     TEXT NOT NULL,
  output_ok    INTEGER                         -- call↔output success: 1/0/NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_hash ON search_chunks(content_hash);

-- contentless-ish FTS over natural-language text (symbols handled separately)
CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5(
  chunk_id UNINDEXED,
  text
);

-- vectors (bge-m3 = 1024 dims). vec0 needs a fixed dim; changing model = rebuild.
CREATE VIRTUAL TABLE IF NOT EXISTS search_vec USING vec0(
  rowid INTEGER PRIMARY KEY,
  embedding FLOAT[1024]
);

-- embedding cache: identical text under same model is embedded once.
CREATE TABLE IF NOT EXISTS embed_cache (
  text_sha TEXT NOT NULL,
  model_id TEXT NOT NULL,
  embedding BLOB NOT NULL,
  PRIMARY KEY (text_sha, model_id)
);
```

- [ ] **Step 4: 运行,确认通过**

Run: `uv run pytest tests/test_search_index.py::test_migration_creates_search_tables -x -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/trajlens/store/migrations/012_search.sql tests/test_search_index.py
git commit -m "feat: add search index migration"
```

---

## Task 3: 符号抽取 symbols.py

**Files:**
- Create: `src/trajlens/search/__init__.py`(空)
- Create: `src/trajlens/search/symbols.py`
- Create: `tests/test_search_symbols.py`

- [ ] **Step 1: 写失败测试**

`tests/test_search_symbols.py`:

```python
from trajlens.search.symbols import extract_symbols


def test_extracts_callee_and_extension():
    syms = extract_symbols('read.csv("data.csv")')
    assert "read.csv" in syms
    assert ".csv" in syms


def test_extracts_pandas_dotted_call():
    assert "pd.read_csv" in extract_symbols("df = pd.read_csv('a.csv')")


def test_command_head_token():
    syms = extract_symbols("pytest tests/ -x", is_command=True)
    assert "pytest" in syms


def test_ignores_unknown_extension():
    # .foobar is not a known data/code ext → not emitted
    assert ".foobar" not in extract_symbols("open('x.foobar')")
```

- [ ] **Step 2: 运行,确认失败**

Run: `uv run pytest tests/test_search_symbols.py -x -q`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现**

`src/trajlens/search/__init__.py`: 空文件。

`src/trajlens/search/symbols.py`:

```python
"""Extract code symbols (callees, libs, commands, file extensions) from tool
calls — the precise-match backbone of trajectory search (design §7)."""
import re

_CALLEE = re.compile(r"\b([A-Za-z_][\w.]*)\s*\(")
_EXT = re.compile(r"\.([A-Za-z][A-Za-z0-9]{0,5})\b")

# known data/code extensions worth indexing; arbitrary extensions are noise
_KNOWN_EXT = {
    "csv", "tsv", "json", "jsonl", "parquet", "xlsx", "xls", "txt", "yaml",
    "yml", "py", "r", "sql", "md", "ipynb", "sh", "js", "ts", "go", "java",
}


def extract_symbols(text: str, *, is_command: bool = False) -> list[str]:
    """Return a sorted, de-duplicated list of symbols found in `text`."""
    syms: set[str] = set()
    for m in _CALLEE.finditer(text):
        syms.add(m.group(1))
    for m in _EXT.finditer(text):
        ext = m.group(1).lower()
        if ext in _KNOWN_EXT:
            syms.add("." + ext)
    if is_command:
        head = text.strip().split()
        if head:
            syms.add(head[0])
    return sorted(syms)
```

- [ ] **Step 4: 运行,确认通过**

Run: `uv run pytest tests/test_search_symbols.py -x -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/trajlens/search/__init__.py src/trajlens/search/symbols.py tests/test_search_symbols.py
git commit -m "feat: symbol extraction for search"
```

---

## Task 4: 投影 + 输出头尾截断 projection.py

**Files:**
- Create: `src/trajlens/search/projection.py`
- Create: `tests/test_search_projection.py`

- [ ] **Step 1: 写失败测试**

`tests/test_search_projection.py`:

```python
from trajlens.core.model import (MessageItem, FunctionCallItem,
                                 FunctionCallOutputItem, ReasoningItem)
from trajlens.search.projection import project_item, truncate_output


def test_truncate_keeps_head_and_tail():
    text = "A" * 100 + "MIDDLE" + "B" * 100
    out = truncate_output(text, head=10, tail=10)
    assert out.startswith("A" * 10)
    assert out.endswith("B" * 10)
    assert "MIDDLE" not in out
    assert "truncated" in out


def test_short_output_unchanged():
    assert truncate_output("short", head=10, tail=10) == "short"


def test_project_function_call_includes_name_and_args():
    it = FunctionCallItem(name="read.csv", arguments='{"path":"a.csv"}', call_id="c1")
    txt = project_item(it)
    assert "read.csv" in txt and "a.csv" in txt


def test_project_message_is_content():
    assert project_item(MessageItem(role="user", content="hello")) == "hello"
```

- [ ] **Step 2: 运行,确认失败**

Run: `uv run pytest tests/test_search_projection.py -x -q`
Expected: FAIL

- [ ] **Step 3: 实现**

`src/trajlens/search/projection.py`:

```python
"""Searchable-text projection per item, with information-density truncation of
long tool outputs (head+tail; the middle of a log/dump is rarely the signal)."""
from trajlens.core.model import Item

_HEAD = 1500
_TAIL = 1500


def truncate_output(text: str, head: int = _HEAD, tail: int = _TAIL) -> str:
    if len(text) <= head + tail:
        return text
    return text[:head] + "\n…[truncated]…\n" + text[-tail:]


def project_item(item: Item) -> str:
    """Natural-language / code text used for FTS + embedding."""
    t = item.type
    if t == "message":
        return item.content
    if t == "reasoning":
        return item.content
    if t == "function_call":
        return f"{item.name} {item.arguments}"
    if t == "function_call_output":
        return truncate_output(item.output)
    return ""
```

- [ ] **Step 4: 运行,确认通过**

Run: `uv run pytest tests/test_search_projection.py -x -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/trajlens/search/projection.py tests/test_search_projection.py
git commit -m "feat: searchable text projection with output truncation"
```

---

## Task 5: chunk 切分(双粒度 + call↔output 配对)chunks.py

**Files:**
- Create: `src/trajlens/search/chunks.py`
- Create: `tests/test_search_chunks.py`

- [ ] **Step 1: 写失败测试**

`tests/test_search_chunks.py`:

```python
from trajlens.core.model import (Trajectory, MessageItem, FunctionCallItem,
                                 FunctionCallOutputItem)
from trajlens.core import grouping
from trajlens.search.chunks import build_chunks


def _traj():
    items = [
        MessageItem(role="user", content="please read the csv"),
        FunctionCallItem(name="read.csv", arguments='{"p":"a.csv"}', call_id="c1"),
        FunctionCallOutputItem(call_id="c1", output="ok 3 rows"),
        FunctionCallItem(name="boom", arguments="{}", call_id="c2"),
        FunctionCallOutputItem(call_id="c2", output="Traceback (most recent call last): Error"),
    ]
    items = grouping.assign_groups(items)
    return Trajectory(content_hash="h" * 64, items=items)


def test_item_chunks_carry_symbols():
    chunks = build_chunks(_traj())
    item_csv = [c for c in chunks if c.granularity == "item" and c.fn_name == "read.csv"]
    assert item_csv and "read.csv" in item_csv[0].symbols


def test_output_ok_paired_by_call_id():
    chunks = build_chunks(_traj())
    by_fn = {c.fn_name: c for c in chunks if c.item_type == "function_call"}
    assert by_fn["read.csv"].output_ok == 1   # "ok 3 rows"
    assert by_fn["boom"].output_ok == 0       # traceback


def test_step_chunks_exist():
    chunks = build_chunks(_traj())
    assert any(c.granularity == "step" for c in chunks)


def test_chunk_id_and_text_sha_stable():
    a = build_chunks(_traj())
    b = build_chunks(_traj())
    assert [c.chunk_id for c in a] == [c.chunk_id for c in b]
```

- [ ] **Step 2: 运行,确认失败**

Run: `uv run pytest tests/test_search_chunks.py -x -q`
Expected: FAIL

- [ ] **Step 3: 实现**

`src/trajlens/search/chunks.py`:

```python
"""Project a Trajectory into searchable chunks at item + step granularity.
function_call chunks carry output_ok, paired with their output via call_id."""
import hashlib
from collections import defaultdict
from dataclasses import dataclass

from trajlens.core.model import Trajectory
from trajlens.search.projection import project_item
from trajlens.search.symbols import extract_symbols

_ERR_MARKERS = ("traceback", "error", "exception", "command failed",
                "non-zero exit", "fatal:")


@dataclass
class Chunk:
    chunk_id: str
    content_hash: str
    granularity: str          # 'item' | 'step'
    idx: int                  # item idx, or step_id
    role: str | None
    item_type: str
    fn_name: str | None
    symbols: str              # space-padded: " a b c "
    text: str
    text_sha: str
    output_ok: int | None


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _output_ok(output: str) -> int:
    low = output.lower()
    return 0 if any(m in low for m in _ERR_MARKERS) else 1


def _pad(syms: list[str]) -> str:
    return (" " + " ".join(syms) + " ") if syms else ""


def build_chunks(traj: Trajectory) -> list[Chunk]:
    ch = traj.content_hash
    items = traj.items

    # pair function_call_output back to its call by call_id
    out_ok: dict[str, int] = {}
    for it in items:
        if it.type == "function_call_output":
            out_ok[it.call_id] = _output_ok(it.output)

    chunks: list[Chunk] = []

    # ── item granularity ──
    for i, it in enumerate(items):
        text = project_item(it)
        if not text.strip():
            continue
        is_cmd = it.type == "function_call" and it.name in ("bash", "shell", "run", "exec")
        if it.type == "function_call":
            syms = extract_symbols(f"{it.name} {it.arguments}", is_command=is_cmd)
        else:
            syms = extract_symbols(text)
        fn_name = it.name if it.type == "function_call" else None
        role = it.role if it.type == "message" else None
        ok = out_ok.get(it.call_id) if it.type == "function_call" else None
        cid = _sha(f"{ch}|item|{i}")
        chunks.append(Chunk(
            chunk_id=cid, content_hash=ch, granularity="item", idx=i,
            role=role, item_type=it.type, fn_name=fn_name,
            symbols=_pad(syms), text=text, text_sha=_sha(text), output_ok=ok))

    # ── step granularity (group assistant-side items by (run_id, step_id)) ──
    steps: dict[tuple, list] = defaultdict(list)
    for it in items:
        if it.step_id is not None:
            steps[(it.run_id, it.step_id)].append(it)
    for sidx, (key, sitems) in enumerate(sorted(steps.items())):
        text = "\n".join(project_item(x) for x in sitems if project_item(x).strip())
        if not text.strip():
            continue
        syms: set[str] = set()
        for x in sitems:
            if x.type == "function_call":
                syms.update(extract_symbols(f"{x.name} {x.arguments}"))
        cid = _sha(f"{ch}|step|{sidx}")
        chunks.append(Chunk(
            chunk_id=cid, content_hash=ch, granularity="step", idx=sidx,
            role=None, item_type="step", fn_name=None,
            symbols=_pad(sorted(syms)), text=text, text_sha=_sha(text), output_ok=None))

    return chunks
```

- [ ] **Step 4: 运行,确认通过**

Run: `uv run pytest tests/test_search_chunks.py -x -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/trajlens/search/chunks.py tests/test_search_chunks.py
git commit -m "feat: dual-granularity chunking with call-output pairing"
```

---

## Task 6: DSL 模型 dsl.py

**Files:**
- Create: `src/trajlens/search/dsl.py`
- Create: `tests/test_search_dsl.py`

- [ ] **Step 1: 写失败测试**

`tests/test_search_dsl.py`:

```python
from trajlens.search.dsl import DSLQuery, Term


def test_parse_full_query():
    q = DSLQuery.model_validate({
        "any": [
            {"text": "read.csv", "scope": {"item_type": "function_call"}, "field": "symbols"},
            {"text": "pd.read_csv", "field": "symbols"},
        ],
        "filters": [{"field": "resolution", "op": "=", "value": "resolved"}],
        "version": 1,
    })
    assert len(q.any) == 2
    assert q.any[0].field == "symbols"
    assert q.any[0].scope["item_type"] == "function_call"
    assert q.filters[0]["field"] == "resolution"


def test_defaults():
    t = Term(text="hello")
    assert t.field == "text" and t.scope == {}
    q = DSLQuery(any=[t])
    assert q.all == [] and q.filters == [] and q.version == 1


def test_roundtrip_json_stable():
    q = DSLQuery(any=[Term(text="x", field="symbols")])
    assert DSLQuery.model_validate_json(q.model_dump_json()) == q
```

- [ ] **Step 2: 运行,确认失败**

Run: `uv run pytest tests/test_search_dsl.py -x -q`
Expected: FAIL

- [ ] **Step 3: 实现**

`src/trajlens/search/dsl.py`:

```python
"""Stable query DSL — the reproducible middle layer. The LLM translator (future
plan) produces it; pipelines (scenario 2) submit it directly."""
from pydantic import BaseModel, Field


class Term(BaseModel):
    text: str
    field: str = "text"          # 'text' (FTS+vector) | 'symbols' (exact)
    scope: dict = Field(default_factory=dict)   # {"item_type": ..., "role": ...}


class DSLQuery(BaseModel):
    any: list[Term] = Field(default_factory=list)   # OR
    all: list[Term] = Field(default_factory=list)   # AND
    # facet filters in repo.query_trajectories format: {field, op, value}
    filters: list[dict] = Field(default_factory=list)
    version: int = 1

    def is_symbol_only(self) -> bool:
        """True when every term targets symbols → vector path can be skipped."""
        terms = self.any + self.all
        return bool(terms) and all(t.field == "symbols" for t in terms)
```

- [ ] **Step 4: 运行,确认通过**

Run: `uv run pytest tests/test_search_dsl.py -x -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/trajlens/search/dsl.py tests/test_search_dsl.py
git commit -m "feat: search DSL model"
```

---

## Task 7: RRF 融合 fusion.py（纯函数）

**Files:**
- Create: `src/trajlens/search/fusion.py`
- Create: `tests/test_search_fusion.py`

- [ ] **Step 1: 写失败测试**

`tests/test_search_fusion.py`:

```python
from trajlens.search.fusion import rrf_fuse


def test_item_in_two_rankings_outranks_single():
    # 'a' appears top in both rankings; 'b' only in one
    scores = rrf_fuse([["a", "b"], ["a", "c"]], k=60)
    assert scores["a"] > scores["b"]
    assert scores["a"] > scores["c"]


def test_empty_rankings():
    assert rrf_fuse([], k=60) == {}
    assert rrf_fuse([[], []], k=60) == {}


def test_rank_position_matters():
    s = rrf_fuse([["x", "y"]], k=60)
    assert s["x"] > s["y"]   # earlier rank = higher score
```

- [ ] **Step 2: 运行,确认失败**

Run: `uv run pytest tests/test_search_fusion.py -x -q`
Expected: FAIL

- [ ] **Step 3: 实现**

`src/trajlens/search/fusion.py`:

```python
"""Reciprocal Rank Fusion — combine ranked lists whose scores aren't comparable
(symbol hits, BM25, vector distance) into one ranking. score = Σ 1/(k+rank)."""


def rrf_fuse(rankings: list[list[str]], k: int = 60) -> dict[str, float]:
    """`rankings`: each is an ordered list of chunk_ids (best first).
    Returns {chunk_id: fused_score}."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, cid in enumerate(ranking):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
    return scores
```

- [ ] **Step 4: 运行,确认通过**

Run: `uv run pytest tests/test_search_fusion.py -x -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/trajlens/search/fusion.py tests/test_search_fusion.py
git commit -m "feat: RRF fusion"
```

---

## Task 8: embedding 客户端 embed.py

**Files:**
- Create: `src/trajlens/search/embed.py`
- Create: `tests/test_search_embed.py`

- [ ] **Step 1: 写失败测试（用 httpx MockTransport,不打真实网络）**

`tests/test_search_embed.py`:

```python
import httpx
import pytest
from trajlens.annotate.llm_client import LLMProfile
from trajlens.search import embed as embmod


@pytest.mark.asyncio
async def test_embed_texts_parses_vectors(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        n = len(httpx.QueryParams())  # unused
        body = request.read()
        import json
        data = json.loads(body)["input"]
        return httpx.Response(200, json={
            "data": [{"embedding": [0.1, 0.2, 0.3]} for _ in data]})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(embmod, "_transport", transport)

    profile = LLMProfile(name="emb", base_url="http://x/v1", api_key="k",
                         model="bge-m3")
    out = await embmod.embed_texts(profile, ["a", "b"])
    assert out == [[0.1, 0.2, 0.3], [0.1, 0.2, 0.3]]
```

- [ ] **Step 2: 运行,确认失败**

Run: `uv run pytest tests/test_search_embed.py -x -q`
Expected: FAIL

- [ ] **Step 3: 实现（复用 llm_client 的限流 + proxy 风格）**

`src/trajlens/search/embed.py`:

```python
"""Async OpenAI-compatible /embeddings client. Mirrors llm_client's rate limiting
and proxy handling. base_url points at a local bge-m3 service (TEI / Ollama)."""
import httpx

from trajlens.annotate.llm_client import (LLMProfile, _get_limiter,
                                           _make_client_kwargs)

# overridable in tests via monkeypatch
_transport: httpx.BaseTransport | None = None


async def embed_texts(profile: LLMProfile, texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts. Returns one vector per input, in order."""
    if not texts:
        return []
    url = profile.base_url.rstrip("/") + "/embeddings"
    headers = {"Authorization": f"Bearer {profile.api_key}"}
    payload = {"model": profile.model, "input": texts}
    kwargs = _make_client_kwargs(profile.proxy, profile.timeout)
    if _transport is not None:
        kwargs["transport"] = _transport
    limiter = _get_limiter()
    async with limiter, httpx.AsyncClient(**kwargs) as client:
        resp = await client.post(url, json=payload, headers=headers)
    resp.raise_for_status()
    data = resp.json()["data"]
    return [d["embedding"] for d in data]
```

- [ ] **Step 4: 运行,确认通过**

Run: `uv run pytest tests/test_search_embed.py -x -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/trajlens/search/embed.py tests/test_search_embed.py
git commit -m "feat: OpenAI-compatible embeddings client"
```

---

## Task 9: 索引构建 index.py

**Files:**
- Create: `src/trajlens/search/index.py`
- Modify: `tests/test_search_index.py`(追加用例)

索引接收一个 `embed_fn(texts) -> list[vector]`（同步包装),便于单测注入 fake；生产用 `embed.embed_texts` 的同步桥接。

- [ ] **Step 1: 写失败测试（fake embedder,4 维,避免依赖真实服务/sqlite-vec 维度）**

追加到 `tests/test_search_index.py`:

```python
from trajlens.core.model import (Trajectory, MessageItem, FunctionCallItem,
                                 FunctionCallOutputItem)
from trajlens.core import grouping
from trajlens.search.index import index_trajectory


def _traj():
    items = grouping.assign_groups([
        MessageItem(role="user", content="read the csv please"),
        FunctionCallItem(name="read.csv", arguments='{"p":"a.csv"}', call_id="c1"),
        FunctionCallOutputItem(call_id="c1", output="ok"),
    ])
    return Trajectory(content_hash="a" * 64, items=items)


def _fake_embed(dim=4):
    # deterministic vector from text length so tests are stable
    return lambda texts: [[float(len(t) % 7), 1.0, 0.0, 0.0] for t in texts]


def test_index_writes_chunks_and_fts(tmp_path):
    conn = dbmod.connect(str(tmp_path / "t.db")); dbmod.migrate(conn)
    n = index_trajectory(conn, _traj(), embed_fn=_fake_embed(), model_id="fake-4", dim=4)
    assert n > 0
    rows = conn.execute("SELECT symbols FROM search_chunks WHERE fn_name='read.csv'").fetchall()
    assert rows and "read.csv" in rows[0]["symbols"]
    fts = conn.execute("SELECT count(*) FROM search_fts").fetchone()[0]
    assert fts > 0


def test_index_is_idempotent(tmp_path):
    conn = dbmod.connect(str(tmp_path / "t.db")); dbmod.migrate(conn)
    index_trajectory(conn, _traj(), embed_fn=_fake_embed(), model_id="fake-4", dim=4)
    before = conn.execute("SELECT count(*) FROM search_chunks").fetchone()[0]
    index_trajectory(conn, _traj(), embed_fn=_fake_embed(), model_id="fake-4", dim=4)
    after = conn.execute("SELECT count(*) FROM search_chunks").fetchone()[0]
    assert before == after   # reindex replaces, doesn't duplicate


def test_embed_cache_reused(tmp_path):
    conn = dbmod.connect(str(tmp_path / "t.db")); dbmod.migrate(conn)
    calls = {"n": 0}
    def counting(texts):
        calls["n"] += len(texts)
        return [[1.0, 0, 0, 0] for _ in texts]
    index_trajectory(conn, _traj(), embed_fn=counting, model_id="fake-4", dim=4)
    first = calls["n"]
    index_trajectory(conn, _traj(), embed_fn=counting, model_id="fake-4", dim=4)
    assert calls["n"] == first   # second run served from embed_cache
```

> 注:`search_vec` 在迁移里固定 1024 维。测试用 4 维 → index 在 `dim != 1024` 或 `conn.vec_ok` 为假时跳过向量写入(仅写 chunk/FTS/cache),用 `index_trajectory(..., dim=4)` 触发该路径。生产 `dim=1024`。

- [ ] **Step 2: 运行,确认失败**

Run: `uv run pytest tests/test_search_index.py -x -q`
Expected: FAIL（`index_trajectory` 不存在）

- [ ] **Step 3: 实现**

`src/trajlens/search/index.py`:

```python
"""Build the search index for one trajectory: chunks → search_chunks + search_fts
(+ search_vec when sqlite-vec is available and dim matches). Embeddings are cached
by (text_sha, model_id) so unchanged text is embedded once."""
import json
import struct

from trajlens.core.model import Trajectory
from trajlens.search.chunks import build_chunks

_VEC_DIM = 1024   # bge-m3


def _pack(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def index_trajectory(conn, traj: Trajectory, *, embed_fn, model_id: str,
                     dim: int = _VEC_DIM) -> int:
    """Returns number of chunks indexed. embed_fn(texts)->list[vector]."""
    ch = traj.content_hash
    chunks = build_chunks(traj)
    if not chunks:
        return 0

    # ── replace any prior index for this trajectory (idempotent reindex) ──
    old = [r["id"] for r in conn.execute(
        "SELECT id FROM search_chunks WHERE content_hash=?", (ch,)).fetchall()]
    if old:
        conn.executemany("DELETE FROM search_fts WHERE chunk_id="
                         "(SELECT chunk_id FROM search_chunks WHERE id=?)",
                         [(i,) for i in old])
        if getattr(conn, "vec_ok", False):
            conn.executemany("DELETE FROM search_vec WHERE rowid=?", [(i,) for i in old])
        conn.execute("DELETE FROM search_chunks WHERE content_hash=?", (ch,))

    # ── insert chunks + FTS ──
    ids: list[int] = []
    for c in chunks:
        cur = conn.execute(
            "INSERT INTO search_chunks(chunk_id, content_hash, granularity, idx,"
            " role, item_type, fn_name, symbols, text, text_sha, output_ok)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (c.chunk_id, c.content_hash, c.granularity, c.idx, c.role,
             c.item_type, c.fn_name, c.symbols, c.text, c.text_sha, c.output_ok))
        ids.append(cur.lastrowid)
        conn.execute("INSERT INTO search_fts(chunk_id, text) VALUES(?,?)",
                     (c.chunk_id, c.text))

    # ── embeddings (cache by text_sha+model_id) → search_vec ──
    use_vec = getattr(conn, "vec_ok", False) and dim == _VEC_DIM
    if use_vec:
        to_embed: list[tuple[int, str, str]] = []   # (rowid, text_sha, text)
        for rowid, c in zip(ids, chunks):
            row = conn.execute(
                "SELECT embedding FROM embed_cache WHERE text_sha=? AND model_id=?",
                (c.text_sha, model_id)).fetchone()
            if row:
                conn.execute("INSERT INTO search_vec(rowid, embedding) VALUES(?,?)",
                             (rowid, row["embedding"]))
            else:
                to_embed.append((rowid, c.text_sha, c.text))
        if to_embed:
            vecs = embed_fn([t[2] for t in to_embed])
            for (rowid, tsha, _), vec in zip(to_embed, vecs):
                blob = _pack(vec)
                conn.execute("INSERT OR REPLACE INTO embed_cache(text_sha, model_id, embedding)"
                             " VALUES(?,?,?)", (tsha, model_id, blob))
                conn.execute("INSERT INTO search_vec(rowid, embedding) VALUES(?,?)",
                             (rowid, blob))
    conn.commit()
    return len(chunks)
```

> 测试里 `dim=4 != _VEC_DIM` → `use_vec` 为假 → 不写 `search_vec`,但 `embed_cache` 也不写。要让 `test_embed_cache_reused` 成立,缓存逻辑必须在 vec 关闭时仍生效。**修正**:把缓存查/写移到 `use_vec` 之外——见下方修订。

- [ ] **Step 3b: 修订实现使缓存独立于 vec 开关**

把上面 `# ── embeddings ──` 段替换为:

```python
    # ── embeddings: always cache by (text_sha, model_id); write search_vec only
    #    when sqlite-vec is usable and dim matches the table. ──
    seen: set[str] = set()
    pending: list[tuple[int, str, str]] = []
    for rowid, c in zip(ids, chunks):
        row = conn.execute(
            "SELECT embedding FROM embed_cache WHERE text_sha=? AND model_id=?",
            (c.text_sha, model_id)).fetchone()
        if row is None and c.text_sha not in seen:
            pending.append((rowid, c.text_sha, c.text))
            seen.add(c.text_sha)
    if pending:
        vecs = embed_fn([t[2] for t in pending])
        for (_, tsha, _), vec in zip(pending, vecs):
            conn.execute("INSERT OR REPLACE INTO embed_cache(text_sha, model_id, embedding)"
                         " VALUES(?,?,?)", (tsha, model_id, _pack(vec)))
    if getattr(conn, "vec_ok", False) and dim == _VEC_DIM:
        for rowid, c in zip(ids, chunks):
            row = conn.execute(
                "SELECT embedding FROM embed_cache WHERE text_sha=? AND model_id=?",
                (c.text_sha, model_id)).fetchone()
            if row:
                conn.execute("INSERT INTO search_vec(rowid, embedding) VALUES(?,?)",
                             (rowid, row["embedding"]))
```

- [ ] **Step 4: 运行,确认通过**

Run: `uv run pytest tests/test_search_index.py -x -q`
Expected: PASS（4 条用例）

- [ ] **Step 5: Commit**

```bash
git add src/trajlens/search/index.py tests/test_search_index.py
git commit -m "feat: build search index with embedding cache"
```

---

## Task 10: 检索执行 query.py（facet + 符号 + FTS + 向量 + RRF + 聚合）

**Files:**
- Create: `src/trajlens/search/query.py`
- Create: `tests/test_search_query.py`

- [ ] **Step 1: 写失败测试（fake embedder;不依赖 sqlite-vec,验证符号+FTS+RRF+聚合+证据）**

`tests/test_search_query.py`:

```python
from trajlens.core.model import (Trajectory, MessageItem, FunctionCallItem,
                                 FunctionCallOutputItem)
from trajlens.core import grouping
from trajlens.store import db as dbmod
from trajlens.search.index import index_trajectory
from trajlens.search.dsl import DSLQuery, Term
from trajlens.search.query import search


def _traj(ch, fn, arg):
    items = grouping.assign_groups([
        MessageItem(role="user", content="do something with data"),
        FunctionCallItem(name=fn, arguments=arg, call_id="c1"),
        FunctionCallOutputItem(call_id="c1", output="ok"),
    ])
    return Trajectory(content_hash=ch, items=items)


def _fake(texts):
    return [[float(len(t) % 7), 1.0, 0.0, 0.0] for t in texts]


def _db(tmp_path):
    conn = dbmod.connect(str(tmp_path / "t.db")); dbmod.migrate(conn)
    index_trajectory(conn, _traj("a"*64, "read.csv", '{"p":"a.csv"}'),
                     embed_fn=_fake, model_id="fake-4", dim=4)
    index_trajectory(conn, _traj("b"*64, "write.json", '{"p":"b.json"}'),
                     embed_fn=_fake, model_id="fake-4", dim=4)
    return conn


def test_symbol_query_finds_read_csv(tmp_path):
    conn = _db(tmp_path)
    q = DSLQuery(any=[Term(text="read.csv", field="symbols")])
    res = search(conn, q, embed_fn=_fake, model_id="fake-4", dim=4)
    hashes = [r["content_hash"] for r in res]
    assert "a"*64 in hashes
    assert "b"*64 not in hashes


def test_result_carries_evidence(tmp_path):
    conn = _db(tmp_path)
    q = DSLQuery(any=[Term(text="read.csv", field="symbols")])
    res = search(conn, q, embed_fn=_fake, model_id="fake-4", dim=4)
    ev = res[0]["evidence"][0]
    assert ev["item_type"] == "function_call"
    assert "read.csv" in ev["symbols"]


def test_fts_text_query(tmp_path):
    conn = _db(tmp_path)
    q = DSLQuery(any=[Term(text="something", field="text")])
    res = search(conn, q, embed_fn=_fake, model_id="fake-4", dim=4)
    assert len(res) == 2   # both have "do something with data"


def test_facet_filter_intersects(tmp_path):
    conn = _db(tmp_path)
    # no annotations seeded → resolution filter yields empty allowed set
    q = DSLQuery(any=[Term(text="read.csv", field="symbols")],
                 filters=[{"field": "resolution", "op": "=", "value": "resolved"}])
    res = search(conn, q, embed_fn=_fake, model_id="fake-4", dim=4)
    assert res == []
```

- [ ] **Step 2: 运行,确认失败**

Run: `uv run pytest tests/test_search_query.py -x -q`
Expected: FAIL

- [ ] **Step 3: 实现**

`src/trajlens/search/query.py`:

```python
"""Execute a DSL query: facet narrow → symbol + FTS + vector recall → RRF fuse →
aggregate to trajectories with hit evidence (design §10)."""
import struct

from trajlens.store import repo
from trajlens.search.dsl import DSLQuery
from trajlens.search.fusion import rrf_fuse

_VEC_DIM = 1024


def _fts_escape(text: str) -> str:
    # quote as an FTS5 phrase; double internal quotes
    return '"' + text.replace('"', '""') + '"'


def _scope_sql(scope: dict) -> tuple[str, list]:
    parts, params = [], []
    if scope.get("item_type"):
        parts.append("c.item_type = ?"); params.append(scope["item_type"])
    if scope.get("role"):
        parts.append("c.role = ?"); params.append(scope["role"])
    return (" AND " + " AND ".join(parts)) if parts else "", params


def _symbol_rank(conn, term, allowed) -> list[str]:
    scope_sql, sp = _scope_sql(term.scope)
    rows = conn.execute(
        "SELECT chunk_id FROM search_chunks c"
        " WHERE c.symbols LIKE ?" + scope_sql,
        [f"% {term.text} %"] + sp).fetchall()
    return [r["chunk_id"] for r in rows
            if allowed is None or _hash_of(conn, r["chunk_id"]) in allowed]


def _fts_rank(conn, term, allowed) -> list[str]:
    scope_sql, sp = _scope_sql(term.scope)
    rows = conn.execute(
        "SELECT f.chunk_id FROM search_fts f"
        " JOIN search_chunks c ON c.chunk_id = f.chunk_id"
        " WHERE search_fts MATCH ?" + scope_sql + " ORDER BY rank",
        [_fts_escape(term.text)] + sp).fetchall()
    return [r["chunk_id"] for r in rows
            if allowed is None or _hash_of(conn, r["chunk_id"]) in allowed]


def _vector_rank(conn, term, embed_fn, model_id, allowed, limit) -> list[str]:
    if not getattr(conn, "vec_ok", False):
        return []
    vec = embed_fn([term.text])[0]
    blob = struct.pack(f"{len(vec)}f", *vec)
    rows = conn.execute(
        "SELECT c.chunk_id FROM search_vec v"
        " JOIN search_chunks c ON c.id = v.rowid"
        " WHERE v.embedding MATCH ? AND k = ? ORDER BY distance",
        (blob, limit * 5)).fetchall()
    return [r["chunk_id"] for r in rows
            if allowed is None or _hash_of(conn, r["chunk_id"]) in allowed]


def _hash_of(conn, chunk_id) -> str:
    r = conn.execute("SELECT content_hash FROM search_chunks WHERE chunk_id=?",
                     (chunk_id,)).fetchone()
    return r["content_hash"] if r else ""


def search(conn, dsl: DSLQuery, *, embed_fn, model_id: str, dim: int = _VEC_DIM,
           limit: int = 50) -> list[dict]:
    # 1. facet narrow (None = unrestricted)
    allowed = None
    if dsl.filters:
        allowed = set(repo.query_matching_hashes(conn, filters=dsl.filters))
        if not allowed:
            return []

    # 2. recall: symbol + FTS + vector, per term
    rankings: list[list[str]] = []
    use_vec = getattr(conn, "vec_ok", False) and dim == _VEC_DIM and not dsl.is_symbol_only()
    for term in (dsl.any + dsl.all):
        if term.field == "symbols":
            rankings.append(_symbol_rank(conn, term, allowed))
        else:
            rankings.append(_fts_rank(conn, term, allowed))
            if use_vec:
                rankings.append(_vector_rank(conn, term, embed_fn, model_id, allowed, limit))

    # 3. RRF fuse chunk rankings
    fused = rrf_fuse(rankings)
    if not fused:
        return []

    # 4. aggregate chunk scores → trajectory (max chunk score wins)
    traj_score: dict[str, float] = {}
    traj_ev: dict[str, list] = {}
    for chunk_id, sc in sorted(fused.items(), key=lambda kv: -kv[1]):
        row = conn.execute(
            "SELECT content_hash, item_type, fn_name, symbols, idx, output_ok, text"
            " FROM search_chunks WHERE chunk_id=?", (chunk_id,)).fetchone()
        if not row:
            continue
        h = row["content_hash"]
        traj_score[h] = max(traj_score.get(h, 0.0), sc)
        traj_ev.setdefault(h, [])
        if len(traj_ev[h]) < 3:   # top-3 evidence chunks per trajectory
            traj_ev[h].append({
                "item_type": row["item_type"], "fn_name": row["fn_name"],
                "symbols": row["symbols"].strip(), "idx": row["idx"],
                "output_ok": row["output_ok"],
                "snippet": row["text"][:200], "score": round(sc, 4)})

    ranked = sorted(traj_score.items(), key=lambda kv: -kv[1])[:limit]
    return [{"content_hash": h, "score": round(s, 4), "evidence": traj_ev[h]}
            for h, s in ranked]
```

- [ ] **Step 4: 运行,确认通过**

Run: `uv run pytest tests/test_search_query.py -x -q`
Expected: PASS（4 条）

- [ ] **Step 5: Commit**

```bash
git add src/trajlens/search/query.py tests/test_search_query.py
git commit -m "feat: DSL search execution with RRF fusion and evidence"
```

---

## Task 11: CLI `index` 命令

**Files:**
- Modify: `src/trajlens/cli.py`(在 `metrics` 命令后追加)
- Create: `tests/test_search_cli.py`

`index` 命令为存量轨迹建索引(backfill)。生产用真实 bge-m3;命令接受 `--model`、`--base-url` 等,默认从 `.env` / `config/llm_profiles.yaml` 的 `embedding` profile 读。

- [ ] **Step 1: 写失败测试（CliRunner + monkeypatch embed,避免网络）**

`tests/test_search_cli.py`:

```python
from typer.testing import CliRunner
from trajlens.cli import app
from trajlens.store import db as dbmod, repo
from trajlens.core.model import Trajectory, MessageItem, FunctionCallItem
from trajlens.core import grouping
import trajlens.search.cli_index as ci   # thin module holding the embed bridge


def test_index_command_builds_index(tmp_path, monkeypatch):
    db = str(tmp_path / "t.db")
    conn = dbmod.connect(db); dbmod.migrate(conn)
    ds = repo.get_or_create_dataset(conn, name="_default")
    b = repo.create_batch(conn, dataset_id=ds["id"], format="x")
    traj = Trajectory(content_hash="a"*64, items=grouping.assign_groups([
        MessageItem(role="user", content="hi"),
        FunctionCallItem(name="read.csv", arguments="{}", call_id="c1")]))
    repo.put_trajectory(conn, traj, batch_id=b["id"]); conn.commit()
    conn.close()

    monkeypatch.setattr(ci, "make_embed_fn",
                        lambda *a, **k: (lambda texts: [[1.0, 0, 0, 0] for _ in texts]))
    monkeypatch.setattr(ci, "EMBED_DIM", 4)

    res = CliRunner().invoke(app, ["index", "--db", db])
    assert res.exit_code == 0, res.output
    conn = dbmod.connect(db)
    assert conn.execute("SELECT count(*) FROM search_chunks").fetchone()[0] > 0
```

- [ ] **Step 2: 运行,确认失败**

Run: `uv run pytest tests/test_search_cli.py -x -q`
Expected: FAIL

- [ ] **Step 3: 实现 —— embed 桥接模块 + CLI 命令**

`src/trajlens/search/cli_index.py`（隔离真实 embedding 桥接,便于测试 monkeypatch）:

```python
"""Bridge: build a sync embed_fn over the async embeddings client + load the
embedding profile. Kept in its own module so the CLI test can monkeypatch it."""
import asyncio

from trajlens.annotate.llm_client import LLMProfile, load_profiles
from trajlens.search import embed as embmod

EMBED_DIM = 1024


def load_embed_profile(name: str = "embedding") -> LLMProfile:
    profiles = load_profiles()
    if name not in profiles:
        raise KeyError(f"no '{name}' profile in config/llm_profiles.yaml")
    return profiles[name]


def make_embed_fn(profile: LLMProfile):
    def _fn(texts):
        return asyncio.run(embmod.embed_texts(profile, texts))
    return _fn
```

`src/trajlens/cli.py` 追加命令:

```python
@app.command()
def index(db: str = _DB, dataset: str = typer.Option("", help="Restrict to a dataset"),
          model_profile: str = typer.Option("embedding", help="LLM profile name for embeddings")):
    """Build the search index (chunks + FTS + vectors) for stored trajectories."""
    from trajlens.store import db as dbmod, repo
    from trajlens.search import cli_index as ci
    from trajlens.search.index import index_trajectory

    conn = dbmod.connect(db)
    dbmod.migrate(conn)
    profile = ci.load_embed_profile(model_profile)
    embed_fn = ci.make_embed_fn(profile)

    ds_id = None
    if dataset:
        row = conn.execute("SELECT id FROM datasets WHERE name=? OR id=?",
                           (dataset, dataset)).fetchone()
        if not row:
            typer.echo(f"dataset '{dataset}' not found", err=True); raise typer.Exit(1)
        ds_id = row["id"]

    hashes = [t["content_hash"] for t in repo.list_trajectories(conn, dataset_id=ds_id)]
    total = 0
    for i, ch in enumerate(hashes):
        traj = repo.get_trajectory(conn, ch)
        if traj:
            total += index_trajectory(conn, traj, embed_fn=embed_fn,
                                      model_id=profile.model, dim=ci.EMBED_DIM)
        if (i + 1) % 50 == 0 or i + 1 == len(hashes):
            typer.echo(f"\r  {i+1}/{len(hashes)} trajectories, {total} chunks",
                       nl=(i+1 == len(hashes)), err=True)
    typer.echo(f"indexed {total} chunks across {len(hashes)} trajectories")
```

- [ ] **Step 4: 运行,确认通过**

Run: `uv run pytest tests/test_search_cli.py -x -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/trajlens/search/cli_index.py src/trajlens/cli.py tests/test_search_cli.py
git commit -m "feat: trajlens index CLI command"
```

---

## Task 12: 查询 API 路由 `POST /api/v1/search`

**Files:**
- Modify: `src/trajlens/api/routes.py`(在 `/api/health` 后追加)
- Create: `tests/test_search_api.py`

- [ ] **Step 1: 写失败测试**

`tests/test_search_api.py`:

```python
from fastapi.testclient import TestClient
from trajlens.api.app import create_app
from trajlens.store import db as dbmod, repo
from trajlens.core.model import Trajectory, MessageItem, FunctionCallItem
from trajlens.core import grouping
from trajlens.search.index import index_trajectory


def _setup(tmp_path):
    db = str(tmp_path / "t.db")
    conn = dbmod.connect(db); dbmod.migrate(conn)
    traj = Trajectory(content_hash="a"*64, items=grouping.assign_groups([
        MessageItem(role="user", content="hi"),
        FunctionCallItem(name="read.csv", arguments="{}", call_id="c1")]))
    repo.put_trajectory(conn, traj); conn.commit()
    index_trajectory(conn, traj, embed_fn=lambda t: [[1.0,0,0,0] for _ in t],
                     model_id="fake-4", dim=4)
    conn.close()
    return db


def test_search_endpoint_returns_hits(tmp_path):
    db = _setup(tmp_path)
    app = create_app(db_path=db)
    client = TestClient(app)
    resp = client.post("/api/v1/search", json={
        "any": [{"text": "read.csv", "field": "symbols"}]})
    assert resp.status_code == 200
    hits = resp.json()["results"]
    assert hits[0]["content_hash"] == "a"*64
    assert "read.csv" in hits[0]["evidence"][0]["symbols"]
```

> 检查 `app.py` 工厂名:若为 `create_app(db_path=...)` 直接用;若不同,按现有签名调整(读 `src/trajlens/api/app.py` 顶部确认)。

- [ ] **Step 2: 运行,确认失败**

Run: `uv run pytest tests/test_search_api.py -x -q`
Expected: FAIL

- [ ] **Step 3: 实现路由**

`src/trajlens/api/routes.py` 在 `health()` 后追加:

```python
@router.post("/api/v1/search")
def search_route(payload: dict = Body(...), conn: sqlite3.Connection = Depends(_conn)):
    """DSL-driven trajectory search. Body = DSL JSON (see search.dsl.DSLQuery)."""
    from trajlens.search.dsl import DSLQuery
    from trajlens.search.query import search as run_search
    from trajlens.search import cli_index as ci

    dsl = DSLQuery.model_validate(payload)
    # symbol-only / facet-only queries skip embeddings entirely
    embed_fn = None
    if not dsl.is_symbol_only():
        try:
            profile = ci.load_embed_profile()
            embed_fn = ci.make_embed_fn(profile)
        except Exception:
            embed_fn = None   # degrade: no vector path
    results = run_search(conn, dsl, embed_fn=embed_fn or (lambda t: []),
                         model_id=getattr(locals().get("profile", None), "model", ""),
                         limit=payload.get("limit", 50))
    return {"results": results}
```

> 注:`embed_fn=lambda t: []` 时 `_vector_rank` 仍受 `conn.vec_ok` 与 `is_symbol_only` 守卫,空 embedder 不会被调用到——symbol/FTS 路照常工作,这就是 spec §14 的降级行为。

- [ ] **Step 4: 运行,确认通过 + 全量回归**

Run: `uv run pytest tests/test_search_api.py -x -q && uv run pytest -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/trajlens/api/routes.py tests/test_search_api.py
git commit -m "feat: search API endpoint"
```

---

## Task 13: 真实长轨迹端到端验证（标 slow,需本地 bge-m3）

**Files:**
- Create: `tests/test_search_e2e.py`

此 task 用 `tests/samples/` 里真实的长 session 轨迹做端到端:ingest → index(真实 bge-m3)→ 用从样本自身抽出的符号搜索 → 断言命中自身。不假设样本内容,因此对任何样本稳健。

- [ ] **Step 1: 写 e2e 测试**

`tests/test_search_e2e.py`:

```python
"""End-to-end search over a real long trajectory. Requires a local bge-m3
embeddings service (set EMBED_BASE_URL/EMBED_MODEL or a 'embedding' profile).
Marked slow — skipped unless RUN_SLOW=1."""
import json
import os
import pathlib

import pytest

from trajlens.adapters import detect_and_parse
from trajlens.store import db as dbmod, repo
from trajlens.search.index import index_trajectory
from trajlens.search.dsl import DSLQuery, Term
from trajlens.search.query import search
from trajlens.search import cli_index as ci

pytestmark = pytest.mark.slow

SAMPLES = pathlib.Path(__file__).parent / "samples"


@pytest.mark.skipif(os.environ.get("RUN_SLOW") != "1", reason="needs local bge-m3")
def test_e2e_real_trajectory_symbol_and_semantic(tmp_path):
    # pick the largest claude_code session (a genuinely long trajectory)
    cc = sorted((SAMPLES / "claude_code").glob("*.jsonl"),
                key=lambda p: p.stat().st_size, reverse=True)
    assert cc, "no claude_code samples"
    raw = [json.loads(ln) for ln in cc[0].read_text().splitlines() if ln.strip()]
    traj, _ = detect_and_parse(raw)

    conn = dbmod.connect(str(tmp_path / "t.db")); dbmod.migrate(conn)
    assert conn.vec_ok, "sqlite-vec must be installed for e2e"
    repo.put_trajectory(conn, traj); conn.commit()

    profile = ci.load_embed_profile()
    embed_fn = ci.make_embed_fn(profile)
    n = index_trajectory(conn, traj, embed_fn=embed_fn, model_id=profile.model)
    assert n > 0

    # 1) symbol path: grab a symbol the trajectory actually contains, search it
    sym_row = conn.execute(
        "SELECT symbols FROM search_chunks WHERE symbols != '' LIMIT 1").fetchone()
    a_symbol = sym_row["symbols"].split()[0]
    res = search(conn, DSLQuery(any=[Term(text=a_symbol, field="symbols")]),
                 embed_fn=embed_fn, model_id=profile.model)
    assert traj.content_hash in [r["content_hash"] for r in res]

    # 2) semantic path: a natural-language query routed through vectors returns it
    res2 = search(conn, DSLQuery(any=[Term(text="read or load a data file", field="text")]),
                  embed_fn=embed_fn, model_id=profile.model)
    assert traj.content_hash in [r["content_hash"] for r in res2]
```

- [ ] **Step 2: 启动本地 bge-m3 并配置 profile**

```bash
# dev: Ollama 跑 bge-m3
ollama pull bge-m3 && ollama serve &   # 暴露 http://localhost:11434/v1
cat >> config/llm_profiles.yaml <<'EOF'
embedding:
  base_url: http://localhost:11434/v1
  api_key: ollama
  model: bge-m3
  proxy: none
EOF
```

- [ ] **Step 3: 运行 e2e**

Run: `RUN_SLOW=1 uv run pytest tests/test_search_e2e.py -x -q -m slow`
Expected: PASS（符号路 + 语义路都命中该真实轨迹）

- [ ] **Step 4: 手动在独立端口验证 UI-less API**

```bash
env $(cat .env.search | xargs) uv run trajlens serve --no-build &   # :8011
curl -s localhost:8011/api/v1/search -H 'content-type: application/json' \
  -d '{"any":[{"text":"read.csv","field":"symbols"}]}' | python -m json.tool
```

Expected: JSON `results` 含命中轨迹 + evidence。

- [ ] **Step 5: Commit**

```bash
git add tests/test_search_e2e.py
git commit -m "test: end-to-end search over real long trajectory"
```

---

## 收尾

- [ ] **全量回归 + typecheck**

```bash
uv run pytest -q          # 全绿(e2e 默认 skip)
make typecheck            # 若项目配置了
```

- [ ] **在干净树验证已提交依赖完整(多 agent 纪律)**

```bash
git worktree add /tmp/verify-search feat/search-core
(cd /tmp/verify-search && uv sync && uv run pytest -q -k search)
git worktree remove /tmp/verify-search
```

- [ ] **推送分支(不自合 main)**

```bash
git push -u origin feat/search-core
```

---

## 后续计划(不在本计划范围)

1. **NL→DSL 翻译**:LLM(复用 `llm_client.chat_completion` + `json_schema`)把自然语言译成 `DSLQuery`,含同义词扩展(`读 csv`→`read.csv/pd.read_csv/...`)+ 静态种子词典兜底。API 加 `POST /api/v1/search/translate`。
2. **搜索 UI**:web/ 加搜索框 + DSL 可编辑双视图 + 命中证据高亮 + 加入数据集。需 `npm run build`。
3. **增量索引接线**:ingest/标注完成后自动投递 index job(复用 `jobs` + `jobqueue`),而非仅手动 `trajlens index --backfill`。
4. **model 版本 staleness**:`model_id` 变更时自动重建向量(照搬 metrics staleness)。

---

## Self-Review

- **Spec 覆盖**:§5 表→Task 2;§6 投影→Task 4;§7 符号→Task 3;§8 配对+截断→Task 4/5;§9 DSL→Task 6;§10 检索+RRF→Task 7/10;§11 索引+缓存→Task 9/11;§13 embedding→Task 8;§14 降级→Task 1(vec)/Task 12(空 embedder);§15 测试→各 task + Task 13。§12 同义词扩展、§4 的 NL 入口→后续计划(已标注,因依赖 LLM)。
- **占位扫描**:无 TBD/TODO;每个 code 步给完整代码。
- **类型一致**:`Chunk` 字段(Task 5)与 `index_trajectory` 写库列(Task 9)、`search` 读库列(Task 10)一致;`embed_fn(texts)->list[vec]` 贯穿 Task 8/9/10/11;`DSLQuery.is_symbol_only` 在 Task 6 定义、Task 10/12 使用。
- **已知收口**:Task 9 的 Step 3→3b 修订把 embed 缓存移出 vec 守卫,保证 `dim=4` 测试下缓存仍生效(测试要求)。
