# Test sample corpus

Curated real-world trajectories, kept in-repo as permanent compatibility fixtures
(exercised by `tests/test_samples.py`). Chosen for **shape diversity**, not volume.

## `openai_messages/` — ingestible now (slice-1 `openai_messages` adapter)

Source: `stepfun2pangu/classified_final` (Step-3.5-Flash-SFT, extended OpenAI SFT format).

| file | shape it exercises |
|---|---|
| `single_fast_en.json` | simplest: system/user/assistant, no reasoning, no tools |
| `single_slow_reasoning.json` | single-turn **with `reasoning_content`** |
| `single_slow_zh.json` | Chinese text (unicode through projection/hash) |
| `multi_fast.json` | multi-turn, no reasoning (→ several runs, 1 step each) |
| `multi_mixed.json` | multi-turn, partial reasoning |
| `agentic_small.json` | **tool_calls + tools**, short agentic loop |
| `agentic_long_run.json` | **113 messages**, 1 user prompt → 56 steps — long-run grouping stress |

## `swe_chat/` — NOT ingestible yet (needs slice-2 `swe_chat` adapter)

Source: `SALT-NLP/SWE-chat-by-agent` (`conversations.parquet`, one row per turn).
One small real session per scaffold, reassembled (ordered by `turn_number`, key columns
kept). Preserved as ready targets for the future raw-log adapter.

| file | scaffold | note |
|---|---|---|
| `claude_code.json` | Claude Code | tool_use / tool_result / file_snapshot / progress |
| `codex.json` | Codex | user_prompt only (this dataset slice has no codex assistant turns) |
| `cursor.json` | Cursor | assistant_response / user_prompt |
| `gemini_cli.json` | Gemini CLI | assistant_response / tool_use / user_prompt |
| `opencode.json` | OpenCode | assistant_response / tool_use / user_prompt |

These rows are raw SWE-chat schema — the future adapter must filter `progress`/`queue_operation`
noise and map `turn_type`/`tool_*` columns into canonical typed items.
