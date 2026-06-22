# traj-lens

Coding-agent trajectory analysis platform. Ingest raw logs from multiple agent formats, normalize to a canonical typed-item model, annotate, compute metrics, and export training data.

## Quick commands

```bash
uv run pytest tests/ -x -q          # run tests (need uv, python 3.12)
uv run trajlens ingest <file>       # ingest JSON/JSONL
uv run trajlens serve               # API on :8000; serves web/dist if built
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
