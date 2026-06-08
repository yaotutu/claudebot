---
name: memory
description: Workspace memory layout for the Claude Code powered personal agent.
always: true
---

# Memory

## Structure

- `CLAUDE.md` — User-facing agent instructions and summarized memory sections.
- `.claude/agent/memory/` — Claudebot-managed memory runtime data. Do NOT edit directly.
- `.claude/agent/memory/chats/` — Per-chat summaries and transcript-derived memory.

## Search Past Events

Memory runtime files under `.claude/agent/memory/` may be JSON or JSONL depending on the subsystem.

- For broad searches, start with `grep(..., path=".claude/agent/memory", glob="*.jsonl", output_mode="count")` or the default `files_with_matches` mode before expanding to full content
- Use `output_mode="content"` plus `context_before` / `context_after` when you need the exact matching lines
- Use `fixed_strings=true` for literal timestamps or JSON fragments
- Use `head_limit` / `offset` to page through long histories
- Use `exec` only as a last-resort fallback when the built-in search cannot express what you need

Examples (replace `keyword`):
- `grep(pattern="keyword", path=".claude/agent/memory", glob="*.jsonl", case_insensitive=true)`
- `grep(pattern="2026-04-02 10:00", path=".claude/agent/memory", glob="*.jsonl", fixed_strings=true)`
- `grep(pattern="keyword", path=".claude/agent/memory", glob="*.jsonl", output_mode="count", case_insensitive=true)`
- `grep(pattern="oauth|token", path=".claude/agent/memory", glob="*.jsonl", output_mode="content", case_insensitive=true)`

## Important

- Do not edit `.claude/agent` directly. Use `agent_runtime` capabilities when available.
- Durable user-facing instructions live in `CLAUDE.md`.
