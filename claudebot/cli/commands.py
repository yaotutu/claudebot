"""CLI commands for claudebot."""

import asyncio
import os
import select
import signal
import sys
import uuid
from contextlib import nullcontext, suppress
from contextvars import ContextVar
from pathlib import Path
from typing import Any

# Force UTF-8 encoding for Windows console
if sys.platform == "win32":
    if sys.stdout.encoding != "utf-8":
        os.environ["PYTHONIOENCODING"] = "utf-8"
        # Re-open stdout/stderr with UTF-8 encoding
        with suppress(Exception):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Keep console encoding setup before importing CLI UI/logging libraries.
import typer  # noqa: E402
from loguru import logger  # noqa: E402

# Remove default handler and re-add with unified claudebot format
logger.remove()
_log_handler_id = logger.add(
    sys.stderr,
    format=(
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <5}</level> | "
        "<cyan>{extra[channel]}</cyan> | "
        "<level>{message}</level>"
    ),
    level="INFO",
    colorize=None,
    filter=lambda record: record["extra"].setdefault("channel", "-") or True,
)

from prompt_toolkit import PromptSession, print_formatted_text  # noqa: E402
from prompt_toolkit.application import run_in_terminal  # noqa: E402
from prompt_toolkit.formatted_text import ANSI, HTML  # noqa: E402
from prompt_toolkit.history import FileHistory  # noqa: E402
from prompt_toolkit.patch_stdout import patch_stdout  # noqa: E402
from rich.console import Console  # noqa: E402
from rich.markdown import Markdown  # noqa: E402
from rich.text import Text  # noqa: E402

from claudebot import __logo__, __version__  # noqa: E402
from claudebot.claude_code.events import ClaudeCodeEvent, EventKind  # noqa: E402
from claudebot.claude_code.project import sync_claude_project  # noqa: E402
from claudebot.claude_code.runner import ClaudeCodeRunner  # noqa: E402
from claudebot.claude_code.sessions import (  # noqa: E402
    ClaudeCodeChatRecord,
    ClaudeCodeSessionStore,
)
from claudebot.cli.stream import StreamRenderer, ThinkingSpinner  # noqa: E402
from claudebot.config.paths import get_workspace_path  # noqa: E402
from claudebot.config.schema import Config  # noqa: E402
from claudebot.utils.restart import (  # noqa: E402
    consume_restart_notice_from_env,
    format_restart_completed_message,
    should_show_cli_restart_notice,
)


def _sanitize_surrogates(text: str) -> str:
    """Reconstruct surrogate pairs into real characters; replace lone surrogates.

    On Windows, console input may produce lone surrogate code points (e.g.
    ``\\ud83d\\udc08`` for U+1F408).  Round-tripping through UTF-16 reconstructs
    paired surrogates into their actual characters and replaces unpaired ones
    with U+FFFD.
    """
    return text.encode("utf-16-le", errors="surrogatepass").decode("utf-16-le", errors="replace")


class SafeFileHistory(FileHistory):
    """FileHistory subclass that sanitizes surrogate characters on write.

    On Windows, special Unicode input (emoji, mixed-script) can produce
    surrogate characters that crash prompt_toolkit's file write.
    See issue #2846.
    """

    def store_string(self, string: str) -> None:
        super().store_string(_sanitize_surrogates(string))


_WEBUI_TURN_META_KEY = "webui_turn_id"
_WEBUI_MESSAGE_SOURCE_META_KEY = "_webui_message_source"
_PROACTIVE_WEBUI_METADATA: ContextVar[dict[str, Any] | None] = ContextVar(
    "proactive_webui_metadata",
    default=None,
)


def _proactive_delivery_metadata(
    channel: str,
    metadata: dict[str, Any] | None,
    *,
    turn_seed: str,
    source_label: str | None = None,
) -> dict[str, Any]:
    """Return channel metadata for a fresh proactive delivery turn."""
    out = dict(metadata or {})
    out.pop(_WEBUI_TURN_META_KEY, None)
    if channel == "websocket":
        out[_WEBUI_TURN_META_KEY] = f"{turn_seed}:{uuid.uuid4().hex}"
        source: dict[str, str] = {"kind": "cron"}
        if source_label:
            source["label"] = source_label
        out[_WEBUI_MESSAGE_SOURCE_META_KEY] = source
    return out


app = typer.Typer(
    name="claudebot",
    context_settings={"help_option_names": ["-h", "--help"]},
    help=f"{__logo__} claudebot - Personal AI Assistant",
    no_args_is_help=True,
)

console = Console()
EXIT_COMMANDS = {"exit", "quit", "/exit", "/quit", ":q"}
_REASONING_SENTENCE_ENDINGS = (".", "!", "?", "。", "！", "？")
_REASONING_FLUSH_CHARS = 60

_HEARTBEAT_PREAMBLE = (
    "[Your response will be delivered directly to the user's messaging app. "
    "Output ONLY the final user-facing message. Never reference internal "
    "files (HEARTBEAT.md, AWARENESS.md, etc.), your instructions, or your "
    "decision process. If nothing needs reporting, respond with just "
    "'All clear.' and nothing else.]\n\n"
)


def _heartbeat_has_active_tasks(content: str) -> bool:
    """True if HEARTBEAT.md has task lines, ignoring headers, blanks and comments."""
    in_comment = False
    in_active_section: bool = False
    for line in content.splitlines():
        stripped = line.strip()
        if in_comment:
            if "-->" in stripped:
                in_comment = False
            continue
        if not stripped or stripped.startswith("#"):
            if stripped.startswith("##") and not stripped.startswith("###"):
                heading = stripped.lstrip("#").strip().lower()
                in_active_section = heading.startswith("active tasks")
            continue
        if stripped.startswith("<!--"):
            if "-->" not in stripped[4:]:
                in_comment = True
            continue
        if in_active_section is False:
            continue
        return True
    return False


# ---------------------------------------------------------------------------
# CLI input: prompt_toolkit for editing, paste, history, and display
# ---------------------------------------------------------------------------

_PROMPT_SESSION: PromptSession | None = None
_SAVED_TERM_ATTRS = None  # original termios settings, restored on exit


def _flush_pending_tty_input() -> None:
    """Drop unread keypresses typed while the model was generating output."""
    try:
        fd = sys.stdin.fileno()
        if not os.isatty(fd):
            return
    except Exception:
        return

    with suppress(Exception):
        import termios

        termios.tcflush(fd, termios.TCIFLUSH)
        return

    with suppress(Exception):
        while True:
            ready, _, _ = select.select([fd], [], [], 0)
            if not ready:
                break
            if not os.read(fd, 4096):
                break


def _restore_terminal() -> None:
    """Restore terminal to its original state (echo, line buffering, etc.)."""
    if _SAVED_TERM_ATTRS is None:
        return
    with suppress(Exception):
        import termios

        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, _SAVED_TERM_ATTRS)


def _init_prompt_session() -> None:
    """Create the prompt_toolkit session with persistent file history."""
    global _PROMPT_SESSION, _SAVED_TERM_ATTRS

    # Save terminal state so we can restore it on exit
    with suppress(Exception):
        import termios

        _SAVED_TERM_ATTRS = termios.tcgetattr(sys.stdin.fileno())

    from claudebot.config.paths import get_cli_history_path

    history_file = get_cli_history_path()
    history_file.parent.mkdir(parents=True, exist_ok=True)

    _PROMPT_SESSION = PromptSession(
        history=SafeFileHistory(str(history_file)),
        enable_open_in_editor=False,
        multiline=False,  # Enter submits (single line mode)
    )


def _make_console() -> Console:
    return Console(file=sys.stdout)


def _render_interactive_ansi(render_fn) -> str:
    """Render Rich output to ANSI so prompt_toolkit can print it safely."""
    ansi_console = Console(
        force_terminal=sys.stdout.isatty(),
        color_system=console.color_system or "standard",
        width=console.width,
    )
    with ansi_console.capture() as capture:
        render_fn(ansi_console)
    return capture.get()


def _print_agent_response(
    response: str,
    render_markdown: bool,
    metadata: dict | None = None,
    show_header: bool = True,
) -> None:
    """Render assistant response with consistent terminal styling."""
    console = _make_console()
    content = response or ""
    body = _response_renderable(content, render_markdown, metadata)
    if show_header:
        console.print()
        console.print(f"[cyan]{__logo__} claudebot[/cyan]")
    console.print(body)
    console.print()


def _response_renderable(content: str, render_markdown: bool, metadata: dict | None = None):
    """Render plain-text command output without markdown collapsing newlines."""
    if not render_markdown:
        return Text(content)
    if (metadata or {}).get("render_as") == "text":
        return Text(content)
    return Markdown(content)


async def _print_interactive_line(text: str) -> None:
    """Print async interactive updates with prompt_toolkit-safe Rich styling."""

    def _write() -> None:
        ansi = _render_interactive_ansi(lambda c: c.print(f"  [dim]↳ {text}[/dim]"))
        print_formatted_text(ANSI(ansi), end="")

    await run_in_terminal(_write)


async def _print_interactive_response(
    response: str,
    render_markdown: bool,
    metadata: dict | None = None,
) -> None:
    """Print async interactive replies with prompt_toolkit-safe Rich styling."""

    def _write() -> None:
        content = response or ""
        ansi = _render_interactive_ansi(
            lambda c: (
                c.print(),
                c.print(f"[cyan]{__logo__} claudebot[/cyan]"),
                c.print(_response_renderable(content, render_markdown, metadata)),
                c.print(),
            )
        )
        print_formatted_text(ANSI(ansi), end="")

    await run_in_terminal(_write)


def _print_cli_progress_line(
    text: str, thinking: ThinkingSpinner | None, renderer: StreamRenderer | None = None
) -> None:
    """Print a CLI progress line, pausing the spinner if needed."""
    if not text.strip():
        return
    target = renderer.console if renderer else console
    pause = (
        renderer.pause_spinner() if renderer else (thinking.pause() if thinking else nullcontext())
    )
    with pause:
        if renderer:
            renderer.ensure_header()
        target.print(f"  [dim]↳ {text}[/dim]")


class _ReasoningBuffer:
    def __init__(self) -> None:
        self._text = ""

    def add(self, text: str) -> str | None:
        if not text:
            return None
        self._text += text
        if self._should_flush(text):
            return self.flush()
        return None

    def flush(self) -> str | None:
        text = self._text.strip()
        self._text = ""
        return text or None

    def clear(self) -> None:
        self._text = ""

    def _should_flush(self, text: str) -> bool:
        stripped = text.rstrip()
        return (
            "\n" in text
            or stripped.endswith(_REASONING_SENTENCE_ENDINGS)
            or len(self._text) >= _REASONING_FLUSH_CHARS
        )


def _print_cli_reasoning(
    text: str, thinking: ThinkingSpinner | None, renderer: StreamRenderer | None = None
) -> None:
    """Print reasoning/thinking content in a distinct style."""
    if not text.strip():
        return
    target = renderer.console if renderer else console
    pause = (
        renderer.pause_spinner() if renderer else (thinking.pause() if thinking else nullcontext())
    )
    with pause:
        if renderer:
            renderer.ensure_header()
        target.print(f"[dim italic]✻ {text}[/dim italic]")


def _flush_cli_reasoning(
    reasoning_buffer: _ReasoningBuffer,
    thinking: ThinkingSpinner | None,
    renderer: StreamRenderer | None = None,
) -> None:
    text = reasoning_buffer.flush()
    if text:
        _print_cli_reasoning(text, thinking, renderer)


async def _print_interactive_progress_line(
    text: str, thinking: ThinkingSpinner | None, renderer: StreamRenderer | None = None
) -> None:
    """Print an interactive progress line, pausing the spinner if needed."""
    if not text.strip():
        return
    if renderer:
        with renderer.pause_spinner():
            renderer.ensure_header()
            renderer.console.print(f"  [dim]↳ {text}[/dim]")
    else:
        with thinking.pause() if thinking else nullcontext():
            await _print_interactive_line(text)


async def _maybe_print_interactive_progress(
    msg: Any,
    thinking: ThinkingSpinner | None,
    channels_config: Any,
    renderer: StreamRenderer | None = None,
    reasoning_buffer: _ReasoningBuffer | None = None,
) -> bool:
    metadata = msg.metadata or {}
    if metadata.get("_retry_wait"):
        await _print_interactive_progress_line(msg.content, thinking, renderer)
        return True

    if not metadata.get("_progress"):
        return False

    reasoning_buffer = reasoning_buffer or _ReasoningBuffer()

    if metadata.get("_reasoning_end"):
        if channels_config and not channels_config.show_reasoning:
            reasoning_buffer.clear()
        else:
            _flush_cli_reasoning(reasoning_buffer, thinking, renderer)
        return True

    is_tool_hint = metadata.get("_tool_hint", False)
    is_reasoning = metadata.get("_reasoning", False) or metadata.get("_reasoning_delta", False)
    if is_reasoning:
        if channels_config and not channels_config.show_reasoning:
            reasoning_buffer.clear()
            return True
        text = reasoning_buffer.add(msg.content)
        if text:
            _print_cli_reasoning(text, thinking, renderer)
        return True
    if channels_config and is_tool_hint and not channels_config.send_tool_hints:
        return True
    if channels_config and not is_tool_hint and not channels_config.send_progress:
        return True

    await _print_interactive_progress_line(msg.content, thinking, renderer)
    return True


def _claude_tool_label(event: ClaudeCodeEvent) -> str:
    if event.kind == EventKind.TOOL_START:
        return f"tool: {event.tool_name}" if event.tool_name else "tool started"
    if event.kind == EventKind.TOOL_RESULT:
        return "tool result"
    if event.kind == EventKind.STATUS:
        return event.text
    if event.kind == EventKind.ERROR:
        return event.text
    return ""


def _claude_chat_record(
    config: Config, session_id: str
) -> tuple[ClaudeCodeSessionStore, ClaudeCodeChatRecord]:
    sync_claude_project(config)
    workspace_path = config.workspace_path
    workspace_path.mkdir(parents=True, exist_ok=True)
    store = ClaudeCodeSessionStore(workspace_path)
    record = store.get_or_create(
        session_id,
        workspace_path=str(workspace_path),
        permission_mode=config.claude_code.permission_mode,
    )
    # Keep the visible claudebot session id stable while letting workspace config
    # changes take effect on the next Claude Code turn.
    record.workspace_path = str(workspace_path)
    return store, record


def _append_claude_transcript(record: ClaudeCodeChatRecord, role: str, content: str) -> None:
    if not content:
        return
    record.transcript.append({"role": role, "content": content})
    record.preview = content[:200]
    if role == "user" and not record.title:
        record.title = content.strip().splitlines()[0][:80]


async def _run_claude_cli_turn(
    config: Config,
    session_id: str,
    prompt: str,
    *,
    renderer: StreamRenderer,
    interactive: bool,
    render_markdown: bool,
) -> str:
    store, record = _claude_chat_record(config, session_id)
    runner = ClaudeCodeRunner(config.claude_code)
    saw_turn_done = False

    async def _on_event(event: ClaudeCodeEvent) -> None:
        nonlocal saw_turn_done
        if event.kind == EventKind.TEXT_DELTA:
            await renderer.on_delta(event.text)
            return
        if event.kind == EventKind.THINKING_DELTA:
            if interactive:
                await _print_interactive_progress_line(event.text, None, renderer)
            else:
                _print_cli_reasoning(event.text, None, renderer)
            return
        if event.kind in {EventKind.TOOL_START, EventKind.TOOL_RESULT, EventKind.STATUS}:
            label = _claude_tool_label(event)
            if not label:
                return
            if interactive:
                await _print_interactive_progress_line(label, None, renderer)
            else:
                _print_cli_progress_line(label, None, renderer)
            return
        if event.kind == EventKind.ERROR:
            label = _claude_tool_label(event)
            if label:
                if interactive:
                    await _print_interactive_progress_line(label, None, renderer)
                else:
                    _print_cli_progress_line(label, None, renderer)
            return
        if event.kind == EventKind.TURN_DONE:
            saw_turn_done = True
            await renderer.on_end()

    result = await runner.run_turn(record, prompt, on_event=_on_event)
    if renderer.streamed and not saw_turn_done:
        await renderer.on_end()
    elif not renderer.streamed:
        await renderer.close()

    _append_claude_transcript(record, "user", prompt)
    _append_claude_transcript(record, "assistant", result.final_text)
    store.save(record)

    if not renderer.streamed and result.final_text:
        if interactive:
            await _print_interactive_response(
                result.final_text,
                render_markdown=render_markdown,
                metadata={},
            )
        else:
            _print_agent_response(
                result.final_text,
                render_markdown=render_markdown,
                metadata={},
            )

    return result.final_text


def _is_exit_command(command: str) -> bool:
    """Return True when input should end interactive chat."""
    return command.lower() in EXIT_COMMANDS


async def _read_interactive_input_async() -> str:
    """Read user input using prompt_toolkit (handles paste, history, display).

    prompt_toolkit natively handles:
    - Multiline paste (bracketed paste mode)
    - History navigation (up/down arrows)
    - Clean display (no ghost characters or artifacts)
    """
    if _PROMPT_SESSION is None:
        raise RuntimeError("Call _init_prompt_session() first")
    try:
        with patch_stdout():
            return await _PROMPT_SESSION.prompt_async(
                HTML("<b fg='ansiblue'>You:</b> "),
            )
    except EOFError as exc:
        raise KeyboardInterrupt from exc


def version_callback(value: bool):
    if value:
        console.print(f"{__logo__} claudebot v{__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(None, "--version", "-v", callback=version_callback, is_eager=True),
):
    """claudebot - Personal AI Assistant."""
    pass


# ============================================================================
# Onboard / Setup
# ============================================================================


@app.command()
def onboard(
    workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
    config: str | None = typer.Option(None, "--config", "-c", help="Path to config file"),
    wizard: bool = typer.Option(False, "--wizard", help="Use interactive wizard"),
):
    """Initialize claudebot configuration and workspace."""
    from claudebot.config.loader import get_config_path, load_config, save_config, set_config_path
    from claudebot.config.schema import Config

    if config:
        config_path = Path(config).expanduser().resolve()
        set_config_path(config_path)
        console.print(f"[dim]Using config: {config_path}[/dim]")
    else:
        config_path = get_config_path()

    def _apply_workspace_override(loaded: Config) -> Config:
        if workspace:
            loaded.workspace.path = workspace
        return loaded

    # Create or update config
    if config_path.exists():
        if wizard:
            config = _apply_workspace_override(load_config(config_path))
        else:
            console.print(f"[yellow]Config already exists at {config_path}[/yellow]")
            console.print(
                "  [bold]y[/bold] = overwrite with defaults (existing values will be lost)"
            )
            console.print(
                "  [bold]N[/bold] = refresh config, keeping existing values and adding new fields"
            )
            if typer.confirm("Overwrite?"):
                config = _apply_workspace_override(Config())
                save_config(config, config_path)
                console.print(f"[green]✓[/green] Config reset to defaults at {config_path}")
            else:
                config = _apply_workspace_override(load_config(config_path))
                save_config(config, config_path)
                console.print(
                    f"[green]✓[/green] Config refreshed at {config_path} (existing values preserved)"
                )
    else:
        config = _apply_workspace_override(Config())
        # In wizard mode, don't save yet - the wizard will handle saving if should_save=True
        if not wizard:
            save_config(config, config_path)
            console.print(f"[green]✓[/green] Created config at {config_path}")

    # Run interactive wizard if enabled
    if wizard:
        from claudebot.cli.onboard import run_onboard

        try:
            result = run_onboard(initial_config=config)
            if not result.should_save:
                console.print("[yellow]Configuration discarded. No changes were saved.[/yellow]")
                return

            config = result.config
            save_config(config, config_path)
            console.print(f"[green]✓[/green] Config saved at {config_path}")
        except Exception as e:
            console.print(f"[red]✗[/red] Error during configuration: {e}")
            console.print(
                "[yellow]Please run 'claudebot onboard' again to complete setup.[/yellow]"
            )
            raise typer.Exit(1)
    _onboard_plugins(config_path)

    # Create workspace, preferring the configured workspace path.
    workspace_path = get_workspace_path(config.workspace_path)
    if not workspace_path.exists():
        workspace_path.mkdir(parents=True, exist_ok=True)
        console.print(f"[green]✓[/green] Created workspace at {workspace_path}")

    sync_claude_project(config, config_path=config_path)

    agent_cmd = 'claudebot agent -m "Hello!"'
    gateway_cmd = "claudebot gateway"
    if config:
        agent_cmd += f" --config {config_path}"
        gateway_cmd += f" --config {config_path}"

    console.print(f"\n{__logo__} claudebot is ready!")
    console.print("\nNext steps:")
    if wizard:
        console.print(f"  1. Chat: [cyan]{agent_cmd}[/cyan]")
        console.print(f"  2. Start gateway: [cyan]{gateway_cmd}[/cyan]")
    else:
        console.print(f"  1. Add your API key to [cyan]{config_path}[/cyan]")
        console.print("     Set claudeCode.apiKey or use Claude Code's own auth.")
        console.print(f"  2. Chat: [cyan]{agent_cmd}[/cyan]")


def _merge_missing_defaults(existing: Any, defaults: Any) -> Any:
    """Recursively fill in missing values from defaults without overwriting user config."""
    if not isinstance(existing, dict) or not isinstance(defaults, dict):
        return existing

    merged = dict(existing)
    for key, value in defaults.items():
        if key not in merged:
            merged[key] = value
        else:
            merged[key] = _merge_missing_defaults(merged[key], value)
    return merged


def _onboard_plugins(config_path: Path) -> None:
    """Legacy channel plugin onboarding is disabled in Claude Code gateway mode."""
    return None


def _claude_model_display(config: Config) -> tuple[str, str]:
    return config.claude_code.model, " (Claude Code)"


def _load_runtime_config(config: str | None = None, workspace: str | None = None) -> Config:
    """Load config and optionally override the active workspace."""
    from claudebot.config.loader import load_config, resolve_config_env_vars, set_config_path

    config_path = None
    if config:
        config_path = Path(config).expanduser().resolve()
        if not config_path.exists():
            console.print(f"[red]Error: Config file not found: {config_path}[/red]")
            raise typer.Exit(1)
        set_config_path(config_path)
        console.print(f"[dim]Using config: {config_path}[/dim]")

    try:
        loaded = resolve_config_env_vars(load_config(config_path))
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)
    _warn_deprecated_config_keys(config_path)
    if workspace:
        loaded.workspace.path = workspace
    return loaded


def _warn_deprecated_config_keys(config_path: Path | None) -> None:
    """Hint users to remove obsolete keys from their config file."""
    import json

    from claudebot.config.loader import get_config_path

    path = config_path or get_config_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return
    if "memoryWindow" in raw.get("agents", {}).get("defaults", {}):
        console.print(
            "[dim]Hint: `memoryWindow` in your config is no longer used "
            "and can be safely removed.[/dim]"
        )


def _migrate_cron_store(config: "Config") -> None:
    """One-time migration: move legacy global cron store into the workspace."""
    from claudebot.config.paths import get_cron_dir

    legacy_path = get_cron_dir() / "jobs.json"
    new_path = config.workspace_path / "cron" / "jobs.json"
    if legacy_path.is_file() and not new_path.exists():
        new_path.parent.mkdir(parents=True, exist_ok=True)
        import shutil

        shutil.move(str(legacy_path), str(new_path))


# ============================================================================
# Gateway / Server
# ============================================================================


@app.command()
def gateway(
    port: int | None = typer.Option(None, "--port", "-p", help="Gateway port"),
    workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
    config: str | None = typer.Option(None, "--config", "-c", help="Path to config file"),
):
    """Start the claudebot gateway."""
    if verbose:
        logger.remove(_log_handler_id)
        logger.add(
            sys.stderr,
            format=(
                "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
                "<level>{level: <5}</level> | "
                "<cyan>{extra[channel]}</cyan> | "
                "<level>{message}</level>"
            ),
            level="DEBUG",
            colorize=None,
            filter=lambda record: record["extra"].setdefault("channel", "-") or True,
        )
    cfg = _load_runtime_config(config, workspace)
    _run_gateway(cfg, port=port)


def _run_gateway(
    config: Config,
    *,
    port: int | None = None,
    open_browser_url: str | None = None,
    webui_static_dist: bool = True,
    health_server_enabled: bool = True,
) -> None:
    """Run the Claude Code WebUI gateway without the legacy AgentLoop."""
    from claudebot.agent_runtime.paths import schedules_path
    from claudebot.bus.queue import MessageBus
    from claudebot.channels.websocket import WebSocketChannel, WebSocketConfig
    from claudebot.cron.service import CronService
    from claudebot.session.manager import SessionManager
    from claudebot.webui.gateway_services import build_gateway_services

    bind_port = port if port is not None else config.gateway.port
    config.gateway.port = bind_port

    console.print(
        f"{__logo__} Starting Claude Code gateway version {__version__} on port {bind_port}..."
    )
    sync_claude_project(config)

    bus = MessageBus()
    session_manager = SessionManager(config.workspace_path)
    extras = dict(getattr(config.channels, "__pydantic_extra__", None) or {})
    websocket_section = extras.get("websocket")
    websocket_data = dict(websocket_section) if isinstance(websocket_section, dict) else {}
    websocket_data.update(
        {
            "enabled": True,
            "host": websocket_data.get("host") or config.gateway.host,
            "port": bind_port,
            "path": websocket_data.get("path") or "/",
            "allow_from": websocket_data.get("allow_from")
            or websocket_data.get("allowFrom")
            or ["*"],
            "streaming": True,
        }
    )
    if not (
        websocket_data.get("token")
        or websocket_data.get("token_issue_path")
        or websocket_data.get("tokenIssuePath")
        or websocket_data.get("token_issue_secret")
        or websocket_data.get("tokenIssueSecret")
    ):
        websocket_data["websocket_requires_token"] = False
    websocket_config = WebSocketConfig.model_validate(websocket_data)

    static_path = None
    if webui_static_dist:
        candidate = Path(__file__).resolve().parent.parent / "web" / "dist"
        static_path = candidate if candidate.exists() else None

    channel_holder: dict[str, WebSocketChannel] = {}

    async def _run_scheduled_agent_turn(job: Any) -> str | None:
        if job.payload.kind != "agent_turn" or not job.payload.message.strip():
            return None
        session_key = job.payload.session_key or (
            f"{job.payload.channel}:{job.payload.to}"
            if job.payload.channel and job.payload.to
            else ""
        )
        if not session_key.startswith("websocket:"):
            return None
        chat_id = session_key.split(":", 1)[1]
        channel_ref = channel_holder.get("channel")
        if channel_ref is None:
            raise RuntimeError("websocket channel is not ready")
        metadata = _proactive_delivery_metadata(
            "websocket",
            job.payload.channel_meta,
            turn_seed=job.id,
            source_label=job.name,
        )
        metadata["webui"] = True
        channel_ref._transcripts.append_user_message(
            chat_id,
            job.payload.message,
            metadata=metadata,
        )
        await channel_ref._run_claude_webui_turn(
            chat_id,
            job.payload.message,
            media_paths=None,
            metadata=metadata,
            workspace_path=config.workspace_path,
        )
        return None

    cron_service = CronService(
        schedules_path(config.workspace_path),
        on_job=_run_scheduled_agent_turn,
    )

    gateway_services = build_gateway_services(
        config=websocket_config,
        bus=bus,
        session_manager=session_manager,
        static_dist_path=static_path,
        workspace_path=config.workspace_path,
        default_restrict_to_workspace=config.tools.restrict_to_workspace,
        disabled_skills=set(config.agents.defaults.disabled_skills),
        runtime_model_name=lambda: config.claude_code.model,
        cron_service=cron_service,
        claude_config=config.claude_code,
        logger=logger,
    )
    channel = WebSocketChannel(websocket_config, bus, gateway=gateway_services)
    channel_holder["channel"] = channel

    async def _health_server(host: str, health_port: int) -> None:
        import json as _json

        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                data = await asyncio.wait_for(reader.read(4096), timeout=5)
            except (asyncio.TimeoutError, ConnectionError):
                writer.close()
                return
            request_line = data.split(b"\r\n", 1)[0].decode("utf-8", errors="replace")
            parts = request_line.split(" ")
            method = parts[0] if len(parts) >= 1 else ""
            path = parts[1] if len(parts) >= 2 else ""
            if method == "GET" and path == "/health":
                body = _json.dumps({"status": "ok"})
                status = "200 OK"
                content_type = "application/json"
            else:
                body = "Not Found"
                status = "404 Not Found"
                content_type = "text/plain"
            resp = (
                f"HTTP/1.0 {status}\r\n"
                f"Content-Type: {content_type}\r\n"
                f"Content-Length: {len(body)}\r\n"
                f"\r\n{body}"
            )
            writer.write(resp.encode())
            await writer.drain()
            writer.close()

        server = await asyncio.start_server(handle, websocket_config.host, health_port)
        console.print(
            f"[green]✓[/green] Health endpoint: http://{websocket_config.host}:{health_port}/health"
        )
        async with server:
            await server.serve_forever()

    async def _open_browser_when_ready() -> None:
        if not open_browser_url:
            return
        import webbrowser

        for _ in range(40):
            try:
                reader, writer = await asyncio.open_connection(websocket_config.host, bind_port)
                writer.close()
                with suppress(Exception):
                    await writer.wait_closed()
                break
            except OSError:
                await asyncio.sleep(0.1)
        try:
            webbrowser.open(open_browser_url)
            console.print(f"[green]✓[/green] Opened browser at {open_browser_url}")
        except Exception as exc:
            console.print(
                f"[yellow]Could not open browser ({exc}); visit {open_browser_url}[/yellow]"
            )

    async def run() -> None:
        tasks: list[asyncio.Task[Any]] = []
        try:
            await cron_service.start()
            tasks.append(asyncio.create_task(channel.start()))
            if health_server_enabled:
                logger.debug("Standalone health server is disabled in Claude Code gateway mode")
            if open_browser_url:
                tasks.append(asyncio.create_task(_open_browser_when_ready()))
            await asyncio.gather(*tasks)
        except KeyboardInterrupt:
            console.print("\nShutting down...")
        except Exception:
            import traceback

            console.print("\n[red]Error: Gateway crashed unexpectedly[/red]")
            console.print(traceback.format_exc())
        finally:
            for task in tasks:
                task.cancel()
            cron_service.stop()
            await channel.stop()
            flushed = session_manager.flush_all()
            if flushed:
                logger.info("Shutdown: flushed {} session(s) to disk", flushed)

    console.print(
        f"[green]✓[/green] WebUI/WS: ws://{websocket_config.host}:{bind_port}{websocket_config.path}"
    )
    console.print(f"[green]✓[/green] Claude Code model: {config.claude_code.model}")
    asyncio.run(run())


# ============================================================================
# Agent Commands
# ============================================================================


@app.command()
def agent(
    message: str = typer.Option(None, "--message", "-m", help="Message to send to the agent"),
    session_id: str = typer.Option("cli:direct", "--session", "-s", help="Session ID"),
    workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
    config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
    markdown: bool = typer.Option(
        True, "--markdown/--no-markdown", help="Render assistant output as Markdown"
    ),
    logs: bool = typer.Option(
        False, "--logs/--no-logs", help="Show claudebot runtime logs during chat"
    ),
):
    """Interact with the agent directly."""
    from loguru import logger

    config = _load_runtime_config(config, workspace)
    sync_claude_project(config)

    if logs:
        logger.enable("claudebot")
    else:
        logger.disable("claudebot")

    restart_notice = consume_restart_notice_from_env()
    if restart_notice and should_show_cli_restart_notice(restart_notice, session_id):
        _print_agent_response(
            format_restart_completed_message(restart_notice.started_at_raw),
            render_markdown=False,
        )

    if message:

        async def run_once():
            renderer = StreamRenderer(
                render_markdown=markdown,
                bot_name=config.agents.defaults.bot_name,
                bot_icon=config.agents.defaults.bot_icon,
            )
            try:
                await _run_claude_cli_turn(
                    config,
                    session_id,
                    message,
                    renderer=renderer,
                    interactive=False,
                    render_markdown=markdown,
                )
            except Exception as exc:
                await renderer.close()
                console.print(f"[red]Error: {exc}[/red]")
                raise typer.Exit(1) from exc

        asyncio.run(run_once())
        return

    _init_prompt_session()
    _model, _preset_tag = _claude_model_display(config)
    console.print(
        f"{__logo__} Interactive mode [bold blue]({_model})[/bold blue]{_preset_tag} "
        "— type [bold]exit[/bold] or [bold]Ctrl+C[/bold] to quit\n"
    )

    def _handle_signal(signum, frame):
        sig_name = signal.Signals(signum).name
        _restore_terminal()
        console.print(f"\nReceived {sig_name}, goodbye!")
        sys.exit(0)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    if hasattr(signal, "SIGHUP"):
        signal.signal(signal.SIGHUP, _handle_signal)
    if hasattr(signal, "SIGPIPE"):
        signal.signal(signal.SIGPIPE, signal.SIG_IGN)

    async def run_interactive():
        renderer: StreamRenderer | None = None
        try:
            while True:
                try:
                    _flush_pending_tty_input()
                    if renderer:
                        renderer.stop_for_input()
                    user_input = _sanitize_surrogates(await _read_interactive_input_async())
                    command = user_input.strip()
                    if not command:
                        continue

                    if _is_exit_command(command):
                        _restore_terminal()
                        console.print("\nGoodbye!")
                        break

                    renderer = StreamRenderer(
                        render_markdown=markdown,
                        bot_name=config.agents.defaults.bot_name,
                        bot_icon=config.agents.defaults.bot_icon,
                    )
                    try:
                        await _run_claude_cli_turn(
                            config,
                            session_id,
                            user_input,
                            renderer=renderer,
                            interactive=True,
                            render_markdown=markdown,
                        )
                    except Exception as exc:
                        await renderer.close()
                        await _print_interactive_progress_line(f"Error: {exc}", None)
                except KeyboardInterrupt:
                    _restore_terminal()
                    console.print("\nGoodbye!")
                    break
                except EOFError:
                    _restore_terminal()
                    console.print("\nGoodbye!")
                    break
        finally:
            if renderer:
                await renderer.close()

    asyncio.run(run_interactive())


# ============================================================================
# Status Commands
# ============================================================================


@app.command()
def status():
    """Show Claude Code gateway status."""
    from claudebot.config.loader import get_config_path, load_config

    config_path = get_config_path()
    config = load_config()
    workspace = config.workspace_path

    console.print(f"{__logo__} claudebot Status\n")
    console.print(
        f"Config: {config_path} {'[green]✓[/green]' if config_path.exists() else '[red]✗[/red]'}"
    )
    console.print(
        f"Workspace: {workspace} {'[green]✓[/green]' if workspace.exists() else '[red]✗[/red]'}"
    )
    console.print(f"Claude Code model: {config.claude_code.model}")
    console.print(f"Claude Code base URL: {config.claude_code.base_url or '[dim]default[/dim]'}")
    console.print(f"Gateway: {config.gateway.host}:{config.gateway.port}")


# ============================================================================
