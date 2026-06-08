---
name: clawhub
description: Search and install agent skills from ClawHub, the public skill registry.
homepage: https://clawhub.ai
metadata: {"claudebot":{"emoji":"🦞"}}
---

# ClawHub

Public skill registry for AI agents. Search by natural language (vector search).

## When to use

Use this skill when the user asks any of:
- "find a skill for …"
- "search for skills"
- "install a skill"
- "what skills are available?"
- "update my skills"

## Search

```bash
npx --yes clawhub@latest search "web scraping" --limit 5
```

## Install

```bash
npx --yes clawhub@latest install <slug> --workdir ~/.claudebot/workspace
```

Replace `<slug>` with the skill name from search results. Install skills into the active workspace and keep them under `.claude/skills/` so Claude Code can load them natively. Always include `--workdir`.

## Update

```bash
npx --yes clawhub@latest update --all --workdir ~/.claudebot/workspace
```

## List installed

```bash
npx --yes clawhub@latest list --workdir ~/.claudebot/workspace
```

## Notes

- Requires Node.js (`npx` comes with it).
- No API key needed for search and install.
- Login (`npx --yes clawhub@latest login`) is only required for publishing.
- `--workdir ~/.claudebot/workspace` is critical — without it, skills install to the current directory instead of the claudebot workspace.
- After install, remind the user to start a new session to load the skill.
