This file is the handoff guide for AI coding agents working on this repository.

## Current Direction

claudebot is an independent Claude Code SDK gateway and personal agent runtime.

The bottom layer must be Claude Code. Do not rebuild a parallel claudebot agent loop, provider stack,
tool executor, or OpenAI-compatible multi-provider runtime. WebUI and CLI should route user turns
through `ClaudeSDKClient`.

## Product Decisions Already Made

- The project is named `claudebot`.
- This repository is independent from its pre-rename history. Do not reintroduce `nanobot`
  commands, config paths, environment variables, docs, or migration compatibility.
- The Python package/distribution name and CLI command are `claudebot`.
- Runtime/product constants live in `claudebot/brand.py`. Use that file for product-facing
  defaults such as config directory, environment variable prefix, and auth header.
- Default config lives at `~/.claudebot/config.json`; default workspace lives at
  `~/.claudebot/workspace`.
- `CLAUDEBOT_` is the product environment variable prefix. `ANTHROPIC_API_KEY` remains the
  standardized Claude/Anthropic API key field and must not be renamed to `CLAUDEBOT_*`.
- Prioritize WebUI and CLI. Legacy multi-channel behavior and OpenAI-compatible API compatibility
  can be removed or broken when they conflict with the Claude Code gateway direction.
- Support only Anthropic/Claude Code compatible auth and protocol surfaces.
- Do not reintroduce `ANTHROPIC_AUTH_TOKEN` as user-facing config.
- Third-party Anthropic-compatible Claude Code endpoints are supported through `claudeCode.baseUrl`.
- Current local test model used during this refactor: `glm-cn/glm-5.1`.
- Each claudebot instance has one default workspace. If `workspace.path` is empty or omitted, the
  workspace is `workspace/` next to the active `config.json`.
- `workspace.allowOutsideWorkspace` defaults to `false`; do not allow workspace escape unless the
  product decision is revisited.
- No old data migration is required unless explicitly requested. Breaking old sessions/configs is
  acceptable during this refactor.
- Claude Code native skills and MCP are part of the design. Do not delete skills/MCP just because
  old claudebot tools were removed.
- Built-in generated skills should use `builtin-*` names.
- Runtime-generated Claude files come from claudebot config. Users should generally edit
  `config.json`, not internal generated `.claude` files.
- WebUI/gateway auth header is `X-Claudebot-Auth`.
- Desktop is not an active product surface. Do not add Electron/native desktop code unless that
  product direction is explicitly reopened.

## Runtime Architecture

### Active Path

1. CLI or WebUI receives a user turn.
2. The gateway resolves the chat workspace.
3. `sync_claude_project()` generates project-local Claude files inside the workspace.
4. `ClaudeCodeRunner` creates a `ClaudeSDKClient`.
5. The runner calls `client.connect()`, `client.query(...)`, streams `client.receive_response()`,
   and then `client.disconnect()`.
6. WebUI/CLI render Claude Code text, reasoning, tool activity, and final result.

Important: standalone `claude_agent_sdk.query()` is the one-shot API and must not be used for the
agent runtime path. The method call `client.query(...)` on `ClaudeSDKClient` is expected.

### Stop Behavior

`/stop` should interrupt the active SDK turn. It must not delete the chat, workspace, or session.
The WebUI path stores an active turn handle and calls `ClaudeSDKClient.interrupt()` through that
handle. If the SDK cannot stop perfectly, return a cancelled/exit-code-130 style result and avoid
saving a final assistant preview for the interrupted turn.

## Config And Local Startup

Default config path:

```text
~/.claudebot/config.json
```

Example third-party Claude Code compatible config:

```json
{
  "claudeCode": {
    "baseUrl": "http://127.0.0.1:20128/v1",
    "apiKey": "${ANTHROPIC_API_KEY}",
    "model": "glm-cn/glm-5.1",
    "enableGatewayModelDiscovery": true,
    "permissionMode": "bypassPermissions"
  },
  "workspace": {
    "path": "",
    "allowOutsideWorkspace": false
  }
}
```

Do not commit real local API keys to the repository. It is fine for a developer machine to keep
them in `~/.claudebot/config.json`.

With the default config above, the default workspace resolves to:

```text
~/.claudebot/workspace
```

Start WebUI/gateway:

```bash
uv run claudebot gateway
```

Open:

```text
http://127.0.0.1:18790
```

Run CLI chat:

```bash
uv run claudebot agent
uv run claudebot agent -m "message"
```

Check runtime status:

```bash
uv run claudebot status
```

## Important Files

- `claudebot/claude_code/runner.py`: Claude Code SDK client runner. Keep this on `ClaudeSDKClient`.
- `claudebot/claude_code/config.py`: Claude Code runtime config and env mapping.
- `claudebot/claude_code/project.py`: Generates workspace Claude project files.
- `claudebot/claude_code/sessions.py`: Claude Code chat metadata store.
- `claudebot/channels/websocket.py`: WebUI transport, `/stop`, active turn handles, event streaming.
- `claudebot/cli/commands.py`: CLI, gateway startup, config loading, workspace override.
- `claudebot/config/schema.py`: Pydantic config schema.
- `claudebot/config/loader.py`: Config loading/saving and config-path-derived runtime context.
- `claudebot/config/paths.py`: Runtime directories derived from active config path.
- `claudebot/webui/settings_api.py`: Settings payload and config updates.
- `webui/`: React/Vite UI.
- `.agent/design.md`, `.agent/security.md`, `.agent/gotchas.md`: local architecture notes.

## Current Git Milestones

Recent commits that define the current direction:

- `1451a4a4 refactor: rename project to claudebot`
- `fc949923 fix: default workspace beside config`
- `4e60bed1 chore: ignore local claude session data`
- `78b59cbd refactor: use claude sdk client for interruptible turns`
- `bc20bab4 refactor: remove provider branding leftovers`
- `7422214c refactor: align gateway slash commands`
- `72c3e1f9 refactor: remove dead legacy provider utilities`
- `d724fc14 docs: align guides with claude code gateway`

## Development Commands

Use `uv run` for Python commands in this repo.

```bash
# Focused backend tests
uv run --extra dev pytest tests/claude_code/test_runner.py tests/channels/test_websocket_channel.py -q

# Broader backend regression used during this refactor
uv run --extra dev pytest tests/config tests/claude_code tests/channels/test_websocket_channel.py \
  tests/channels/test_websocket_http_routes.py tests/cli tests/utils -q

# Full backend regression
uv run --extra dev pytest -q

# Lint changed Python files
uv run --extra dev ruff check claudebot/ tests/

# WebUI tests
cd webui && bun run test

# WebUI build
cd webui && bun run build
```

Known WebUI build warnings currently accepted:

- circular chunk warning between `markdown-vendor` and `syntax-highlight`
- large `index` chunk warning

## Code Style And Workflow

- Python 3.11+, asyncio throughout.
- Line length: 100.
- Ruff rules: E, F, I, N, W; E501 ignored.
- pytest uses `asyncio_mode = "auto"`.
- Prefer focused tests for each phase, then run a broader regression before committing.
- Work directly in the repo unless the user explicitly asks for a worktree.
- Do not revert unrelated user changes.
- Do not commit local runtime data such as `claude-code-sessions/`, `sessions/`, or local
  credentials.
- Do not commit generated dependency folders such as `.venv/` or `webui/node_modules/`.

## Things To Avoid Reintroducing

- The `nanobot` package name, command, config directory, environment variable prefix, docs, or
  migration compatibility.
- Legacy provider registry/model catalog as a user-facing concept.
- OpenAI API compatibility as a core requirement.
- Old claudebot tool execution loop as the main agent engine.
- Standalone `claude_agent_sdk.query()` in runtime paths.
- Separate user-maintained Claude project config that conflicts with claudebot-generated config.
- Global Claude Code config loading when project-local generated config should be used.
