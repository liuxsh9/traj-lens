# Slice 1 — Backend Skeleton Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the end-to-end backend spine — ingest a trajectory (OpenAI/panguml2 `messages` shape) → canonical typed-item model → content-addressed identity → SQLite store (dedup) → FastAPI `GET` returns canonical items with derived step/run grouping.

**Architecture:** Two-layer content-addressed model (design §3). A flat ordered list of typed items is the analysis truth; `content_hash` (sha256 over a volatile-meta-excluded projection) is the trajectory identity and dedup key. step/run grouping is a deterministic projection over the flat items (§3.5), computed in `core/` and carried in the DTO. Extension points are registries (§5.3); slice 1 ships one adapter.

**Tech Stack:** Python 3.12+, uv, Pydantic v2 (models + discriminated union), stdlib `sqlite3` (WAL + `PRAGMA user_version` migrations), FastAPI + uvicorn, typer (CLI), pytest + httpx (tests).

---

> **⚠️ Environment note (this machine):** the Claude Code Bash sandbox blocks PyPI (`uv sync`), GitHub, and `.git` writes. So **dependency install, `pytest` runs, and `git commit` happen in YOUR terminal**, not in-session. The agent writes the code files; you run install/test/commit. Each task's "Run" and "Commit" steps are written for whoever executes in a real terminal. Confirm the execution model at handoff.

> **Spec source of truth:** `docs/superpowers/specs/2026-06-21-traj-lens-design.md`. This plan implements slice 1 of §9.4 (backend portion).

## File Structure

```
pyproject.toml                         # uv project, deps, console script
src/trajlens/
  __init__.py
  core/
    __init__.py
    model.py        # Item discriminated union, Trajectory, Provenance, parse_item
    identity.py     # content projection + content_hash (sha256)
    grouping.py     # assign_groups(): step/run projection over flat items (§3.5)
    registry.py     # generic Registry (dict + duplicate guard)
  adapters/
    __init__.py     # ADAPTERS registry + detect_and_parse()
    openai_messages.py  # OpenAI ChatCompletions / panguml2 messages -> Trajectory
  store/
    __init__.py
    db.py           # connect() (WAL pragmas) + migrate() (user_version runner)
    migrations/001_init.sql
    repo.py         # put_trajectory (dedup) / get_trajectory / list_trajectories
  api/
    __init__.py
    app.py          # FastAPI app factory + get_conn dependency
    routes.py       # /api/health, /api/v1/trajectories (POST/GET), /{hash} (GET)
  cli.py            # typer: ingest, serve
tests/
  conftest.py
  fixtures/panguml2_weather.json
  test_identity.py
  test_grouping.py
  test_adapter_openai.py
  test_store.py
  test_api.py
  test_cli.py
```

Each file has one responsibility; `core/` is pure (no I/O, no network), so identity/grouping/model are unit-testable in isolation.

---

### Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `src/trajlens/__init__.py`, `src/trajlens/core/__init__.py`, `src/trajlens/adapters/__init__.py` (empty for now), `src/trajlens/store/__init__.py`, `src/trajlens/api/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "trajlens"
version = "0.0.1"
description = "Coding-agent trajectory analysis platform"
requires-python = ">=3.12"
dependencies = [
  "pydantic>=2.7",
  "fastapi>=0.110",
  "uvicorn>=0.29",
  "typer>=0.12",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "httpx>=0.27"]

[project.scripts]
trajlens = "trajlens.cli:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/trajlens"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

- [ ] **Step 2: Create empty package files**

Create each `__init__.py` listed above as an empty file. Create `src/trajlens/store/migrations/` directory.

- [ ] **Step 3: Create `tests/conftest.py`**

```python
import pathlib
FIXTURES = pathlib.Path(__file__).parent / "fixtures"
```

- [ ] **Step 4: Install and verify**

Run: `uv sync --extra dev`
Then: `uv run python -c "import trajlens; print('ok')"`
Expected: prints `ok`

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/trajlens tests/conftest.py
git commit -m "chore: scaffold trajlens package (uv, pydantic, fastapi, typer)"
```

---

### Task 2: Core model — typed items + Trajectory

**Files:**
- Create: `src/trajlens/core/model.py`
- Test: `tests/test_grouping.py` is later; this task's behavior is covered by Task 3/4 tests, plus one round-trip test here.
- Test: add `tests/test_model.py`

- [ ] **Step 1: Write the failing test** — `tests/test_model.py`

```python
from trajlens.core.model import (
    Trajectory, MessageItem, FunctionCallItem, parse_item,
)

def test_discriminated_round_trip():
    items = [
        MessageItem(role="user", content="hi"),
        FunctionCallItem(name="Read", arguments='{"path":"a.py"}', call_id="c1"),
    ]
    t = Trajectory(content_hash="h", items=items, tools=[], meta={})
    dumped = t.model_dump()
    assert dumped["items"][0]["type"] == "message"
    assert dumped["items"][1]["type"] == "function_call"

def test_parse_item_rebuilds_subtype():
    it = parse_item({"type": "reasoning", "content": "think"})
    assert it.type == "reasoning"
    assert it.content == "think"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_model.py -v`
Expected: FAIL with `ModuleNotFoundError: trajlens.core.model`

- [ ] **Step 3: Write `src/trajlens/core/model.py`**

```python
from typing import Annotated, Literal, Union
from pydantic import BaseModel, Field, TypeAdapter


class Provenance(BaseModel):
    content_hash: str = ""
    origin: str
    raw_sha: str | None = None


class _Grouped(BaseModel):
    # filled by grouping.assign_groups (projection, not persisted) — §3.5
    step_id: int | None = None
    run_id: int | None = None
    provenance: Provenance | None = None


class MessageItem(_Grouped):
    type: Literal["message"] = "message"
    role: Literal["system", "user", "assistant", "developer"]
    content: str


class ReasoningItem(_Grouped):
    type: Literal["reasoning"] = "reasoning"
    content: str


class FunctionCallItem(_Grouped):
    type: Literal["function_call"] = "function_call"
    name: str
    arguments: str
    call_id: str


class FunctionCallOutputItem(_Grouped):
    type: Literal["function_call_output"] = "function_call_output"
    call_id: str
    output: str


Item = Annotated[
    Union[MessageItem, ReasoningItem, FunctionCallItem, FunctionCallOutputItem],
    Field(discriminator="type"),
]

_ItemAdapter = TypeAdapter(Item)


def parse_item(payload: dict, provenance: dict | None = None) -> Item:
    data = dict(payload)
    if provenance:
        data["provenance"] = provenance
    return _ItemAdapter.validate_python(data)


class Trajectory(BaseModel):
    content_hash: str
    items: list[Item]
    tools: list[dict] = Field(default_factory=list)
    meta: dict = Field(default_factory=dict)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_model.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/trajlens/core/model.py tests/test_model.py
git commit -m "feat(core): typed item model + Trajectory (pydantic discriminated union)"
```

---

### Task 3: Identity — content projection + content_hash

**Files:**
- Create: `src/trajlens/core/identity.py`
- Test: `tests/test_identity.py`

This is the single most correctness-critical unit (design §3.3): the projection MUST exclude volatile meta (timestamps, token usage, scaffold ids, `call_id`) or dedup permanently misses.

- [ ] **Step 1: Write the failing test** — `tests/test_identity.py`

```python
from trajlens.core.identity import content_hash
from trajlens.core.model import (
    MessageItem, ReasoningItem, FunctionCallItem, FunctionCallOutputItem, Provenance,
)

def _convo(call_id, ts_origin):
    return [
        MessageItem(role="system", content="You are an agent."),
        MessageItem(role="user", content="Read a.py"),
        FunctionCallItem(name="Read", arguments='{"path": "a.py"}', call_id=call_id,
                         provenance=Provenance(origin=ts_origin)),
        FunctionCallOutputItem(call_id=call_id, output="print(1)"),
    ]

def test_volatile_meta_excluded_same_hash():
    # different call_id + different provenance.origin -> SAME content hash
    a = content_hash(_convo("call_aaa", "x"))
    b = content_hash(_convo("call_zzz", "y"))
    assert a == b

def test_argument_whitespace_normalized():
    a = content_hash([FunctionCallItem(name="f", arguments='{"a":1,"b":2}', call_id="1")])
    b = content_hash([FunctionCallItem(name="f", arguments='{"b": 2, "a": 1}', call_id="2")])
    assert a == b

def test_different_content_differs():
    a = content_hash([MessageItem(role="user", content="hi")])
    b = content_hash([MessageItem(role="user", content="bye")])
    assert a != b

def test_tools_included():
    items = [MessageItem(role="user", content="hi")]
    a = content_hash(items, tools=[])
    b = content_hash(items, tools=[{"type": "function", "function": {"name": "f"}}])
    assert a != b
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_identity.py -v`
Expected: FAIL with `ModuleNotFoundError: trajlens.core.identity`

- [ ] **Step 3: Write `src/trajlens/core/identity.py`**

```python
import hashlib
import json


def _canonical_args(arguments: str) -> str:
    try:
        return json.dumps(json.loads(arguments), sort_keys=True,
                          ensure_ascii=False, separators=(",", ":"))
    except (json.JSONDecodeError, TypeError):
        return arguments


def _semantic(item) -> dict:
    # Excludes volatile meta: call_id, provenance, step/run, timestamps, token usage.
    # function_call <-> output pairing is preserved by ORDER, not id.
    if item.type == "message":
        return {"k": "m", "role": item.role, "content": item.content}
    if item.type == "reasoning":
        return {"k": "r", "content": item.content}
    if item.type == "function_call":
        return {"k": "c", "name": item.name, "arguments": _canonical_args(item.arguments)}
    if item.type == "function_call_output":
        return {"k": "o", "output": item.output}
    raise ValueError(f"unknown item type: {item.type}")


def content_hash(items, tools=None) -> str:
    projection = {"tools": tools or [], "items": [_semantic(it) for it in items]}
    blob = json.dumps(projection, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_identity.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/trajlens/core/identity.py tests/test_identity.py
git commit -m "feat(core): content_hash identity with volatile-meta exclusion"
```

---

### Task 4: Grouping — step/run projection (§3.5)

**Files:**
- Create: `src/trajlens/core/grouping.py`
- Test: `tests/test_grouping.py`

Proves the "1 user + N steps, not 2 cards" property for distilled single-prompt long runs (§12.3).

- [ ] **Step 1: Write the failing test** — `tests/test_grouping.py`

```python
from trajlens.core.grouping import assign_groups
from trajlens.core.model import (
    MessageItem, ReasoningItem, FunctionCallItem, FunctionCallOutputItem,
)

def _long_run():
    # 1 user prompt, then an autonomous run of 2 think-act-observe steps
    return [
        MessageItem(role="user", content="fix it"),
        ReasoningItem(content="step A think"),
        FunctionCallItem(name="Read", arguments="{}", call_id="c1"),
        FunctionCallOutputItem(call_id="c1", output="..."),
        ReasoningItem(content="step B think"),
        FunctionCallItem(name="Edit", arguments="{}", call_id="c2"),
        FunctionCallOutputItem(call_id="c2", output="..."),
        MessageItem(role="assistant", content="done"),
    ]

def test_single_prompt_long_run_not_two_groups():
    g = assign_groups(_long_run())
    assert g[0].run_id is None and g[0].step_id is None          # user turn
    assert all(it.run_id == 0 for it in g[1:])                   # one assistant run
    steps = {it.step_id for it in g[1:]}
    assert steps == {0, 1}                                       # two steps, not one blob

def test_reasoning_starts_new_step():
    g = assign_groups(_long_run())
    # step 0 = think A + Read + output ; step 1 = think B + Edit + output + msg
    assert [it.step_id for it in g[1:]] == [0, 0, 0, 1, 1, 1, 1]

def test_tool_loop_without_reasoning_splits_on_second_act():
    items = [
        MessageItem(role="user", content="loop"),
        FunctionCallItem(name="Bash", arguments="{}", call_id="a"),
        FunctionCallOutputItem(call_id="a", output="fail"),
        FunctionCallItem(name="Bash", arguments="{}", call_id="b"),
        FunctionCallOutputItem(call_id="b", output="ok"),
    ]
    g = assign_groups(items)
    assert [it.step_id for it in g[1:]] == [0, 0, 1, 1]

def test_second_user_turn_opens_new_run():
    items = [
        MessageItem(role="user", content="a"),
        FunctionCallItem(name="X", arguments="{}", call_id="1"),
        MessageItem(role="user", content="b"),
        FunctionCallItem(name="Y", arguments="{}", call_id="2"),
    ]
    g = assign_groups(items)
    assert g[1].run_id == 0
    assert g[3].run_id == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_grouping.py -v`
Expected: FAIL with `ModuleNotFoundError: trajlens.core.grouping`

- [ ] **Step 3: Write `src/trajlens/core/grouping.py`**

```python
USER_ROLES = {"user", "system", "developer"}


def assign_groups(items):
    """Deterministic step/run projection over the flat item list (design §3.5).

    - user/system/developer message -> run_id=None, step_id=None (a "user turn")
    - assistant-side items group into runs; a run = the autonomous segment after a user turn
    - within a run, a step = one think-act-observe cycle:
        a new step starts at a `reasoning` item, or at a `function_call` that follows
        an observed `function_call_output` (a new act after observing).
    Returns a NEW list of item copies with step_id/run_id set; inputs untouched.
    """
    out = []
    run = -1
    in_user_segment = True
    step = 0
    step_has_output = False

    for it in items:
        if it.type == "message" and it.role in USER_ROLES:
            in_user_segment = True
            out.append(it.model_copy(update={"run_id": None, "step_id": None}))
            continue

        # assistant-side item (reasoning / function_call / function_call_output / assistant message)
        if in_user_segment:
            run += 1
            in_user_segment = False
            step = 0
            step_has_output = False
        else:
            if it.type == "reasoning":
                step += 1
                step_has_output = False
            elif it.type == "function_call" and step_has_output:
                step += 1
                step_has_output = False

        if it.type == "function_call_output":
            step_has_output = True

        out.append(it.model_copy(update={"run_id": run, "step_id": step}))

    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_grouping.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/trajlens/core/grouping.py tests/test_grouping.py
git commit -m "feat(core): step/run grouping projection (1 user + N steps for long runs)"
```

---

### Task 5: Generic registry

**Files:**
- Create: `src/trajlens/core/registry.py`
- Test: `tests/test_registry.py`

- [ ] **Step 1: Write the failing test** — `tests/test_registry.py`

```python
import pytest
from trajlens.core.registry import Registry

def test_register_and_get():
    r = Registry()
    r.register("a", 1)
    assert r.get("a") == 1
    assert "a" in r
    assert r.keys() == ["a"]

def test_duplicate_rejected():
    r = Registry()
    r.register("a", 1)
    with pytest.raises(KeyError):
        r.register("a", 2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: trajlens.core.registry`

- [ ] **Step 3: Write `src/trajlens/core/registry.py`**

```python
class Registry:
    """Dict-with-a-duplicate-guard. Extension points are registries (design §5.3)."""

    def __init__(self):
        self._d: dict = {}

    def register(self, key: str, value):
        if key in self._d:
            raise KeyError(f"duplicate registration: {key}")
        self._d[key] = value
        return value

    def get(self, key):
        return self._d[key]

    def items(self):
        return list(self._d.items())

    def keys(self):
        return list(self._d.keys())

    def __contains__(self, key):
        return key in self._d
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_registry.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/trajlens/core/registry.py tests/test_registry.py
git commit -m "feat(core): generic Registry"
```

---

### Task 6: openai_messages adapter

**Files:**
- Create: `src/trajlens/adapters/openai_messages.py`
- Modify: `src/trajlens/adapters/__init__.py`
- Create: `tests/fixtures/panguml2_weather.json`
- Test: `tests/test_adapter_openai.py`

- [ ] **Step 1: Create the fixture** — `tests/fixtures/panguml2_weather.json`

```json
{
  "version": "2.0.0",
  "meta_info": {"teacher": "glm-5-thinking", "category": "agent"},
  "tools": [{"type": "function", "function": {"name": "get_weather"}}],
  "messages": [
    {"role": "system", "content": "weather assistant"},
    {"role": "user", "content": "weather in Beijing?"},
    {"role": "assistant", "content": "",
     "reasoning_content": "call the weather tool",
     "tool_calls": [{"id": "call_bj", "type": "function",
                     "function": {"name": "get_weather", "arguments": "{\"location\":\"Beijing\"}"}}]},
    {"role": "tool", "tool_call_id": "call_bj", "content": "{\"temp\":\"22C\"}"},
    {"role": "assistant", "content": "It is 22C in Beijing."}
  ]
}
```

- [ ] **Step 2: Write the failing test** — `tests/test_adapter_openai.py`

```python
import json
from tests.conftest import FIXTURES
from trajlens.adapters import detect_and_parse

def _load():
    return json.loads((FIXTURES / "panguml2_weather.json").read_text())

def test_parses_into_typed_items():
    t = detect_and_parse(_load())
    types = [it.type for it in t.items]
    assert types == [
        "message",            # system
        "message",            # user
        "reasoning",          # assistant.reasoning_content
        "function_call",      # assistant.tool_calls[0]
        "function_call_output",  # tool
        "message",            # final assistant
    ]

def test_provenance_and_hash_set():
    t = detect_and_parse(_load())
    assert len(t.content_hash) == 64
    fc = next(it for it in t.items if it.type == "function_call")
    assert fc.provenance.origin == "messages[2].tool_calls[0]"
    assert fc.provenance.content_hash == t.content_hash
    assert t.meta["teacher"] == "glm-5-thinking"

def test_tool_output_keeps_call_pairing():
    t = detect_and_parse(_load())
    call = next(it for it in t.items if it.type == "function_call")
    out = next(it for it in t.items if it.type == "function_call_output")
    assert call.call_id == out.call_id == "call_bj"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_adapter_openai.py -v`
Expected: FAIL with `ImportError: cannot import name 'detect_and_parse'`

- [ ] **Step 4: Write `src/trajlens/adapters/openai_messages.py`**

```python
import json

from trajlens.core import identity
from trajlens.core.model import (
    Trajectory, MessageItem, ReasoningItem, FunctionCallItem,
    FunctionCallOutputItem, Provenance,
)


def sniff(raw) -> bool:
    return isinstance(raw, dict) and isinstance(raw.get("messages"), list)


def _as_text(content) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False)


def parse(raw: dict) -> Trajectory:
    messages = raw["messages"]
    tools = raw.get("tools", []) or []
    items = []

    def p(origin):
        return Provenance(origin=origin)

    for mi, m in enumerate(messages):
        role = m.get("role")
        if role in ("system", "user", "developer"):
            items.append(MessageItem(role=role, content=_as_text(m.get("content")),
                                      provenance=p(f"messages[{mi}]")))
        elif role == "assistant":
            rc = m.get("reasoning_content")
            if rc:
                items.append(ReasoningItem(content=rc,
                                           provenance=p(f"messages[{mi}].reasoning_content")))
            for ci, tc in enumerate(m.get("tool_calls") or []):
                fn = tc.get("function", {})
                items.append(FunctionCallItem(
                    name=fn.get("name", ""), arguments=fn.get("arguments", "") or "",
                    call_id=tc.get("id") or f"m{mi}_c{ci}",
                    provenance=p(f"messages[{mi}].tool_calls[{ci}]")))
            content = m.get("content")
            if content:
                items.append(MessageItem(role="assistant", content=_as_text(content),
                                         provenance=p(f"messages[{mi}].content")))
        elif role == "tool":
            items.append(FunctionCallOutputItem(
                call_id=m.get("tool_call_id") or "", output=_as_text(m.get("content")),
                provenance=p(f"messages[{mi}]")))

    ch = identity.content_hash(items, tools)
    for it in items:
        if it.provenance:
            it.provenance.content_hash = ch
    return Trajectory(content_hash=ch, items=items, tools=tools,
                      meta=raw.get("meta_info", {}) or {})
```

- [ ] **Step 5: Write `src/trajlens/adapters/__init__.py`**

```python
from trajlens.core.registry import Registry
from . import openai_messages

ADAPTERS = Registry()
ADAPTERS.register("openai_messages", openai_messages)


def detect_and_parse(raw):
    """Sniff registered adapters and parse with the first match."""
    for _name, mod in ADAPTERS.items():
        if mod.sniff(raw):
            return mod.parse(raw)
    raise ValueError("no adapter matched the input shape")
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/test_adapter_openai.py -v`
Expected: PASS (3 passed)

- [ ] **Step 7: Commit**

```bash
git add src/trajlens/adapters tests/test_adapter_openai.py tests/fixtures/panguml2_weather.json
git commit -m "feat(adapters): openai_messages adapter + detect_and_parse registry"
```

---

### Task 7: Store — db connect + migrations

**Files:**
- Create: `src/trajlens/store/db.py`
- Create: `src/trajlens/store/migrations/001_init.sql`
- Test: `tests/test_store.py` (db portion)

- [ ] **Step 1: Write the failing test** — `tests/test_store.py`

```python
from trajlens.store import db as dbmod

def test_migrate_creates_tables_and_sets_version(tmp_path):
    conn = dbmod.connect(str(tmp_path / "t.db"))
    v = dbmod.migrate(conn)
    assert v == 1
    names = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"trajectories", "ingestions", "raw_blobs", "items"} <= names

def test_migrate_is_idempotent(tmp_path):
    conn = dbmod.connect(str(tmp_path / "t.db"))
    assert dbmod.migrate(conn) == 1
    assert dbmod.migrate(conn) == 1  # second run is a no-op

def test_wal_enabled(tmp_path):
    conn = dbmod.connect(str(tmp_path / "t.db"))
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_store.py -v`
Expected: FAIL with `ModuleNotFoundError: trajlens.store.db`

- [ ] **Step 3: Write `src/trajlens/store/migrations/001_init.sql`**

```sql
CREATE TABLE IF NOT EXISTS trajectories (
  content_hash TEXT PRIMARY KEY,
  items_count  INTEGER NOT NULL,
  tools        TEXT NOT NULL DEFAULT '[]',
  meta         TEXT NOT NULL DEFAULT '{}',
  created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ingestions (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  content_hash TEXT NOT NULL REFERENCES trajectories(content_hash),
  source_path  TEXT,
  raw_sha      TEXT,
  ingested_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_blobs (
  raw_sha TEXT PRIMARY KEY,
  path    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS items (
  content_hash TEXT NOT NULL REFERENCES trajectories(content_hash),
  idx          INTEGER NOT NULL,
  type         TEXT NOT NULL,
  payload      TEXT NOT NULL,
  provenance   TEXT,
  PRIMARY KEY (content_hash, idx)
);
```

- [ ] **Step 4: Write `src/trajlens/store/db.py`**

```python
import pathlib
import sqlite3

MIGRATIONS_DIR = pathlib.Path(__file__).parent / "migrations"


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def migrate(conn: sqlite3.Connection) -> int:
    """Run *.sql in migrations/ whose NNN prefix exceeds PRAGMA user_version."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for f in sorted(MIGRATIONS_DIR.glob("*.sql")):
        n = int(f.name.split("_")[0])
        if n > version:
            conn.executescript(f.read_text())
            conn.execute(f"PRAGMA user_version={n}")
            conn.commit()
            version = n
    return version
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_store.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Commit**

```bash
git add src/trajlens/store/db.py src/trajlens/store/migrations/001_init.sql tests/test_store.py
git commit -m "feat(store): sqlite connect (WAL) + user_version migration runner"
```

---

### Task 8: Store — repo (put/get/list with dedup)

**Files:**
- Create: `src/trajlens/store/repo.py`
- Test: append to `tests/test_store.py`

- [ ] **Step 1: Write the failing test** — append to `tests/test_store.py`

```python
import json
from tests.conftest import FIXTURES
from trajlens.store import repo
from trajlens.adapters import detect_and_parse

def _ingest(conn, blob_dir):
    raw_bytes = (FIXTURES / "panguml2_weather.json").read_bytes()
    traj = detect_and_parse(json.loads(raw_bytes))
    return repo.put_trajectory(conn, traj, source_path="x.json",
                               raw_bytes=raw_bytes, blob_dir=str(blob_dir))

def test_put_is_idempotent_by_content_hash(tmp_path):
    conn = dbmod.connect(str(tmp_path / "t.db")); dbmod.migrate(conn)
    h1 = _ingest(conn, tmp_path / "blobs")
    h2 = _ingest(conn, tmp_path / "blobs")
    assert h1 == h2
    n_traj = conn.execute("SELECT COUNT(*) FROM trajectories").fetchone()[0]
    n_ing = conn.execute("SELECT COUNT(*) FROM ingestions").fetchone()[0]
    assert n_traj == 1   # deduped
    assert n_ing == 2    # both ingestions recorded

def test_get_returns_items_with_grouping(tmp_path):
    conn = dbmod.connect(str(tmp_path / "t.db")); dbmod.migrate(conn)
    h = _ingest(conn, tmp_path / "blobs")
    t = repo.get_trajectory(conn, h)
    assert t is not None
    assert [it.type for it in t.items][0] == "message"
    # grouping populated on read: the user turn has run_id None, assistant items run 0
    assert t.items[1].run_id is None          # user
    assert t.items[2].run_id == 0             # reasoning (assistant run)

def test_get_missing_returns_none(tmp_path):
    conn = dbmod.connect(str(tmp_path / "t.db")); dbmod.migrate(conn)
    assert repo.get_trajectory(conn, "nope") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_store.py -v`
Expected: FAIL with `ModuleNotFoundError: trajlens.store.repo`

- [ ] **Step 3: Write `src/trajlens/store/repo.py`**

```python
import datetime
import hashlib
import json
import pathlib

from trajlens.core import grouping
from trajlens.core.model import Trajectory, parse_item


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


def put_trajectory(conn, traj: Trajectory, *, source_path=None,
                   raw_bytes: bytes | None = None, blob_dir: str | None = None) -> str:
    """Insert trajectory+items if new (dedup by content_hash); always record an ingestion."""
    ch = traj.content_hash
    exists = conn.execute(
        "SELECT 1 FROM trajectories WHERE content_hash=?", (ch,)).fetchone()

    raw_sha = None
    if raw_bytes is not None and blob_dir is not None:
        raw_sha = hashlib.sha256(raw_bytes).hexdigest()
        d = pathlib.Path(blob_dir)
        d.mkdir(parents=True, exist_ok=True)
        fp = d / raw_sha
        if not fp.exists():
            fp.write_bytes(raw_bytes)
        conn.execute("INSERT OR IGNORE INTO raw_blobs(raw_sha, path) VALUES(?, ?)",
                     (raw_sha, str(fp)))

    if not exists:
        conn.execute(
            "INSERT INTO trajectories(content_hash, items_count, tools, meta, created_at)"
            " VALUES(?, ?, ?, ?, ?)",
            (ch, len(traj.items), json.dumps(traj.tools), json.dumps(traj.meta), _now()))
        for i, it in enumerate(traj.items):
            payload = it.model_dump(exclude={"provenance", "step_id", "run_id"})
            prov = it.provenance.model_dump() if it.provenance else None
            conn.execute(
                "INSERT INTO items(content_hash, idx, type, payload, provenance)"
                " VALUES(?, ?, ?, ?, ?)",
                (ch, i, it.type, json.dumps(payload),
                 json.dumps(prov) if prov else None))

    conn.execute(
        "INSERT INTO ingestions(content_hash, source_path, raw_sha, ingested_at)"
        " VALUES(?, ?, ?, ?)", (ch, source_path, raw_sha, _now()))
    conn.commit()
    return ch


def get_trajectory(conn, content_hash: str) -> Trajectory | None:
    row = conn.execute(
        "SELECT * FROM trajectories WHERE content_hash=?", (content_hash,)).fetchone()
    if not row:
        return None
    rows = conn.execute(
        "SELECT * FROM items WHERE content_hash=? ORDER BY idx", (content_hash,)).fetchall()
    items = [parse_item(json.loads(r["payload"]),
                        json.loads(r["provenance"]) if r["provenance"] else None)
             for r in rows]
    items = grouping.assign_groups(items)   # grouping is a read-time projection (§3.5)
    return Trajectory(content_hash=content_hash, items=items,
                      tools=json.loads(row["tools"]), meta=json.loads(row["meta"]))


def list_trajectories(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT content_hash, items_count, created_at FROM trajectories"
        " ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_store.py -v`
Expected: PASS (6 passed total in file)

- [ ] **Step 5: Commit**

```bash
git add src/trajlens/store/repo.py tests/test_store.py
git commit -m "feat(store): repo put/get/list with content_hash dedup + read-time grouping"
```

---

### Task 9: API — FastAPI ingest/get/list/health

**Files:**
- Create: `src/trajlens/api/app.py`
- Create: `src/trajlens/api/routes.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write the failing test** — `tests/test_api.py`

```python
import json
from fastapi.testclient import TestClient
from tests.conftest import FIXTURES
from trajlens.api.app import create_app

def _client(tmp_path):
    app = create_app(db_path=str(tmp_path / "t.db"), blob_dir=str(tmp_path / "blobs"))
    return TestClient(app)

def test_health(tmp_path):
    c = _client(tmp_path)
    assert c.get("/api/health").json() == {"status": "ok"}

def test_ingest_then_get(tmp_path):
    c = _client(tmp_path)
    raw = json.loads((FIXTURES / "panguml2_weather.json").read_text())
    r = c.post("/api/v1/trajectories", json=raw)
    assert r.status_code == 200
    ch = r.json()["content_hash"]
    assert len(ch) == 64

    got = c.get(f"/api/v1/trajectories/{ch}").json()
    assert got["content_hash"] == ch
    assert got["items"][2]["type"] == "reasoning"
    assert got["items"][2]["run_id"] == 0          # grouping present in DTO

def test_ingest_is_idempotent(tmp_path):
    c = _client(tmp_path)
    raw = json.loads((FIXTURES / "panguml2_weather.json").read_text())
    h1 = c.post("/api/v1/trajectories", json=raw).json()["content_hash"]
    h2 = c.post("/api/v1/trajectories", json=raw).json()["content_hash"]
    assert h1 == h2
    assert len(c.get("/api/v1/trajectories").json()) == 1

def test_get_missing_404(tmp_path):
    c = _client(tmp_path)
    assert c.get("/api/v1/trajectories/nope").status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_api.py -v`
Expected: FAIL with `ModuleNotFoundError: trajlens.api.app`

- [ ] **Step 3: Write `src/trajlens/api/routes.py`**

```python
from fastapi import APIRouter, Body, HTTPException, Request

from trajlens.adapters import detect_and_parse
from trajlens.store import repo

router = APIRouter()


@router.get("/api/health")
def health():
    return {"status": "ok"}


@router.post("/api/v1/trajectories")
def ingest(request: Request, raw: dict = Body(...)):
    conn = request.app.state.conn
    blob_dir = request.app.state.blob_dir
    try:
        traj = detect_and_parse(raw)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    ch = repo.put_trajectory(conn, traj, source_path="inline",
                             raw_bytes=None, blob_dir=blob_dir)
    return {"content_hash": ch, "items_count": len(traj.items)}


@router.get("/api/v1/trajectories")
def list_all(request: Request):
    return repo.list_trajectories(request.app.state.conn)


@router.get("/api/v1/trajectories/{content_hash}")
def get_one(request: Request, content_hash: str):
    traj = repo.get_trajectory(request.app.state.conn, content_hash)
    if traj is None:
        raise HTTPException(status_code=404, detail="not found")
    return traj.model_dump()
```

- [ ] **Step 4: Write `src/trajlens/api/app.py`**

```python
from fastapi import FastAPI

from trajlens.store import db as dbmod
from trajlens.api.routes import router


def create_app(db_path: str = "trajlens.db", blob_dir: str = "blobs") -> FastAPI:
    app = FastAPI(title="traj-lens", version="0.0.1")
    conn = dbmod.connect(db_path)
    dbmod.migrate(conn)
    app.state.conn = conn
    app.state.blob_dir = blob_dir
    app.include_router(router)
    return app


app = create_app()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_api.py -v`
Expected: PASS (5 passed)

- [ ] **Step 6: Commit**

```bash
git add src/trajlens/api tests/test_api.py
git commit -m "feat(api): FastAPI ingest/get/list/health (idempotent, grouping in DTO)"
```

---

### Task 10: CLI — ingest + serve

**Files:**
- Create: `src/trajlens/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test** — `tests/test_cli.py`

```python
import json
from typer.testing import CliRunner
from tests.conftest import FIXTURES
from trajlens.cli import app
from trajlens.store import db as dbmod, repo

runner = CliRunner()

def test_ingest_prints_hash_and_stores(tmp_path):
    src = tmp_path / "in.jsonl"
    src.write_text((FIXTURES / "panguml2_weather.json").read_text())
    db = tmp_path / "t.db"
    result = runner.invoke(app, ["ingest", str(src),
                                 "--db", str(db), "--blob-dir", str(tmp_path / "blobs")])
    assert result.exit_code == 0
    ch = result.stdout.strip().splitlines()[-1]
    assert len(ch) == 64

    conn = dbmod.connect(str(db))
    assert repo.get_trajectory(conn, ch) is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: trajlens.cli`

- [ ] **Step 3: Write `src/trajlens/cli.py`**

```python
import json
import pathlib

import typer

app = typer.Typer(help="traj-lens CLI")


@app.command()
def ingest(path: str, db: str = "trajlens.db", blob_dir: str = "blobs"):
    """Ingest a JSON object or JSONL file (one trajectory per line)."""
    from trajlens.adapters import detect_and_parse
    from trajlens.store import db as dbmod, repo

    conn = dbmod.connect(db)
    dbmod.migrate(conn)
    text = pathlib.Path(path).read_text()
    lines = [ln for ln in text.splitlines() if ln.strip()] or [text]
    for ln in lines:
        raw_bytes = ln.encode("utf-8")
        traj = detect_and_parse(json.loads(ln))
        ch = repo.put_trajectory(conn, traj, source_path=path,
                                 raw_bytes=raw_bytes, blob_dir=blob_dir)
        typer.echo(ch)


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000):
    """Run the API + (later) hosted web."""
    import uvicorn
    uvicorn.run("trajlens.api.app:app", host=host, port=port)


if __name__ == "__main__":
    app()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add src/trajlens/cli.py tests/test_cli.py
git commit -m "feat(cli): typer ingest (json/jsonl) + serve"
```

---

### Task 11: Full suite + manual smoke

**Files:** none (verification only)

- [ ] **Step 1: Run the whole suite**

Run: `uv run pytest -v`
Expected: ALL pass (model 2, identity 4, grouping 4, registry 2, adapter 3, store 6, api 5, cli 1).

- [ ] **Step 2: Manual end-to-end smoke**

```bash
uv run trajlens ingest tests/fixtures/panguml2_weather.json --db /tmp/tl.db --blob-dir /tmp/tlblobs
# copy the printed hash, then:
uv run trajlens serve &
curl -s localhost:8000/api/v1/trajectories | python -m json.tool
curl -s localhost:8000/api/v1/trajectories/<hash> | python -m json.tool   # items have step_id/run_id
kill %1
```
Expected: list shows one trajectory; get returns the typed items with `run_id`/`step_id` populated.

- [ ] **Step 3: Commit any cleanup**

```bash
git add -A && git commit -m "test: slice-1 backend skeleton green end-to-end" || echo "nothing to commit"
```

---

## Self-Review

**Spec coverage (slice 1 backend, §9.4):**
- core 模型 → Task 2 ✓ · content_hash → Task 3 ✓ · step/run 投影 §3.5 → Task 4 ✓ · 注册表 §5.3 → Task 5 ✓
- adapter (openai_messages, 替代 §9.4 的 CC-first，见顶部 scope 说明) → Task 6 ✓
- store WAL + 迁移 runner §10.C.9 → Task 7 ✓ · 仓储 CRUD + dedup → Task 8 ✓
- 最小 API ingest/get + health §9.5 → Task 9 ✓ · CLI → Task 10 ✓
- **Deferred (by design):** 最小 web (linear render, §12.2 A) → separate plan 1b; 标注/指标/导出/裁剪 → slices 2–4; CC adapter → next adapter; SQLite single-writer discipline §10.C.8 → slice 2 (async runner); rich viewer §12 → post-slice-2.

**Placeholder scan:** none — every code step has complete code; every run step has an exact command + expected result.

**Type consistency:** `Trajectory{content_hash, items, tools, meta}`, `Provenance{content_hash, origin, raw_sha}`, item subtypes with `step_id/run_id` via `_Grouped`, `parse_item(payload, provenance)`, `content_hash(items, tools)`, `assign_groups(items)`, `detect_and_parse(raw)`, adapter `sniff(raw)/parse(raw)`, `db.connect(path)/migrate(conn)`, `repo.put_trajectory(conn, traj, *, source_path, raw_bytes, blob_dir)/get_trajectory(conn, ch)/list_trajectories(conn)`, `create_app(db_path, blob_dir)` — names are used consistently across Tasks 2→10.

---

## Notes for the executor

- **Sandbox caveat (this machine):** install/test/commit run in a real terminal; the in-session agent can write files but cannot reach PyPI/GitHub or write `.git`.
- **Grouping is read-time only** — never persisted (design §3.5); `items` table stores payload without `step_id/run_id`.
- **`call_id` is excluded from `content_hash`** on purpose (volatile); function_call↔output pairing is positional. If a future adapter relies on id-based pairing, pair at parse time, not at hash time.
