# traj-lens

Coding-agent trajectory analysis platform. Ingest raw logs from multiple agent formats, normalize to a canonical typed-item model, annotate, compute metrics, and export training data.

## Quick commands

```bash
uv run pytest tests/ -x -q          # run tests (need uv, python 3.12)
uv run trajlens ingest <file>       # ingest JSON/JSONL
uv run trajlens serve               # API on :8000; auto-builds stale web/dist, then serves it
cd web && npm run build              # build frontend (Vite+React+TS)
cd web && npm run dev                # dev server on :5173, proxies /api→:8000
```

## Architecture

```
src/trajlens/
  core/           # model.py (Item discriminated union, Trajectory), identity.py, grouping.py, registry.py
  adapters/       # openai_messages, claude_code, codex — each has sniff()+parse()
  store/          # db.py (SQLite WAL), repo.py, migrations/
  api/            # FastAPI routes + app factory; StaticFiles serves web/dist
  cli.py          # typer CLI: ingest, serve
web/              # Vite + React + TS viewer
tests/samples/    # curated real-world fixtures (openai_messages, claude_code, codex, swe_chat)
docs/superpowers/specs/  # authoritative design doc
```

## Key design rules

- **Two-layer content-addressed model**: raw bytes (export truth) + Items-canonical (analysis truth). Never cross-write.
- **content_hash** = sha256 of semantic projection (excludes call_id, provenance, step/run, timestamps).
- **step/run grouping** is a read-time projection (`core/grouping.py`), never stored.
- **Ponytail mode**: stdlib first, fewest files, shortest diff. Mark deliberate simplifications with `# ponytail:` comments.
- **Adapters**: each has `sniff(raw) -> bool` and `parse(raw) -> Trajectory`. Register in `adapters/__init__.py`.

## Conventions

- Python 3.12+, Pydantic v2, FastAPI, typer, SQLite.
- Tests: `uv run pytest`. Curated samples in `tests/samples/` serve as compatibility regression.
- No unnecessary abstractions. No interface with one implementation.
- Use `from __future__ import annotations` only if needed for <3.10 compat (we target 3.12).

## Sample debugging cheatsheet

DB file: `trajlens.db` (SQLite). Key lookup by `content_hash`.

```sql
-- 1. Trajectory metadata
SELECT items_count, meta FROM trajectories WHERE content_hash = ?;

-- 2. Trajectory-level annotations (resolution, topic, hard_interruption, etc.)
SELECT annotator_id, value FROM annotations WHERE target_hash = ?;  -- target_hash = content_hash

-- 3. Computed metrics (success_score, tool_count, turn_count, etc.)
SELECT metric_id, value FROM metrics WHERE content_hash = ?;

-- 4. Turn/step-level annotation targets
SELECT target_hash, target_type, target_idx FROM annotation_targets WHERE content_hash = ?;
-- Then query annotations for each target_hash to get per-step labels/scores.

-- 5. Ingestion source
SELECT source_path, batch_id FROM ingestions WHERE content_hash = ?;
```

Score formula (`success_score`): `{resolved:100, partially_resolved:50, unresolved:0}[resolution] - min(pushback_count * 5, base * 0.5)`. Logic in `metrics/builtins.py`.

## Frontend build is NOT automatic — rebuild `web/dist` whenever frontend source changes

`web/dist` is a gitignored Vite build artifact. `trajlens serve` only *statically
serves* it — it never compiles. Pulling/pushing source does **not** touch `web/dist`.
So if the served bundle is older than `web/src`, the browser runs stale JS against a
newer API and you get silent breakage (e.g. an "undefined imported" upload toast when
the response shape changed under an old bundle). A real production incident: prod was
fixed by `npm run build` alone, without pulling any new source — the source was already
current, only the bundle was stale.

**Root-cause fix (automatic):** `trajlens serve` now detects a stale/missing `web/dist`
on startup (any build input under `web/` newer than the bundle) and runs `npm run build`
itself before serving. Missing npm or a failed build warns loudly but never blocks
serving the existing bundle. Pass `--no-build` to skip (e.g. prod with a prebuilt dist
and no node). So a plain `git pull && trajlens serve` always serves a fresh bundle.

**Still rebuild manually when you don't go through `serve`:** CI/deploy that copies
`web/dist` to a static host, or a `serve` already running when you edit `web/src` (the
check only runs at startup). Then: `cd web && npm run build`.

Verify the served bundle matches source — `curl -s http://HOST/ | grep -o 'assets/[^"]*\.js'`
should point at a freshly built hash. `index.html` is served `no-cache` and assets
`immutable` (see `api/app.py`), so once the bundle is rebuilt every browser picks it up
on next load — no hard-refresh needed. Stale browsers were the second half of the same
incident, now prevented by those headers.

## Git workflow

- **All changes must be committed** — never leave meaningful work as unstaged modifications across sessions.
- **Commit message format**: `<type>: <concise summary>` (lowercase, no period). Types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`.
- **Group commits logically** — one concern per commit (e.g. "adapter refactor + its test fixes" is one commit, not five). Don't mix unrelated changes.
- **Commit order matters** — if commit B depends on commit A (e.g. migration before the code that uses it), commit A first.
- **Push after committing** unless explicitly told otherwise.
- Generated artifacts (`e2e_blobs/`, `__pycache__/`, `*.db`) stay in `.gitignore`, never committed.
