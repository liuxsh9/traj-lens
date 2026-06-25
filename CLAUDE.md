# traj-lens

Coding-agent trajectory analysis platform. Ingest raw logs from multiple agent formats, normalize to a canonical typed-item model, annotate, compute metrics, and export training data.

## Quick commands

```bash
make help                           # list all dev/ops tasks (install, test, build, deploy…)
uv run pytest tests/ -x -q          # run tests (need uv, python 3.12)
uv run trajlens ingest <file>       # ingest JSON/JSONL
uv run trajlens serve               # API on :8000; auto-builds stale web/dist, then serves it
cd web && npm run build              # build frontend (Vite+React+TS)
cd web && npm run dev                # dev server on :5173, proxies /api→:8000
make deploy                         # server-side upgrade: pull, sync, rebuild web, restart
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

### Multiple agents editing at once (standard workflow)

This repo is often edited by several AI agents in parallel. **One service rule:
exactly one server runs — `make serve` on :8000 in the main checkout. Agents
never `serve`.** This keeps a single live UI and avoids port / `trajlens.db`
collisions. Two roles:

**Agent in a worktree (does the coding):**
1. `make worktree NAME=<task>` — creates `../tl-<task>` on branch `feat/<task>`,
   isolated files of your own. (A branch alone does NOT isolate — all branches
   share the main checkout's files; only a worktree gives you separate files.)
2. Edit there. Verify with `make test` / `make typecheck`. **Never `make serve`**
   — there is only one shared server; you don't need a port to write code.
3. Commit with `git add -p` — stage ONLY your own hunks. NEVER `git add <whole-file>`
   or `git add -A`: in a shared tree that sweeps in another agent's in-flight work
   and ships partial features. (Incident 2026-06-24: a whole-file add pushed a
   `routes.py` calling `jobqueue.submit_cpu` before that function was committed.)
4. Push your branch. Do NOT merge to main yourself.

**Integrator on the main checkout (merges + QA, serially):**
1. `make integrate BR=feat/<task>` — merges the branch and runs the suite.
2. Restart `make serve` (or `make smoke`) to eyeball the one live UI on :8000.
3. Push main. Then take the next branch — one at a time, never parallel merges.
4. Before pushing anything risky, sanity-check in a clean tree, not the dirty
   working tree (a dirty tree masks missing committed deps → false "import OK"):
   `git worktree add /tmp/verify origin/main && (cd /tmp/verify && make test)`.

When in doubt with only 2–3 small changes, skip parallelism — edit serially in
the main checkout, one commit+push at a time. It's often faster than coordinating.
