"""
Hook registry — defines hook events, per-tool hook handlers, and dispatch logic.

Each agent tool (Claude, Gemini, Codex, Cursor, etc.) has its own hook config
file and hook event names. This module abstracts that into a unified interface.
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional

from ..core.paths import CONFIG_DIR


# ──────────────────────────────────────────────────────────────────────────────
# Hook events
# ──────────────────────────────────────────────────────────────────────────────


class HookEvent(str, Enum):
    """All supported hook events across tools."""
    # Claude /通用
    SESSION_START = "sessionStart"
    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    STOP = "Stop"
    NOTIFICATION = "Notification"
    # Codex
    CODEX_SESSION_START = "session_start"
    CODEX_PRE_TOOL = "pre_tool_call"
    CODEX_POST_TOOL = "post_tool_call"
    # Gemini
    GEMINI_SESSION_START = "session_start"
    GEMINI_PRE_TOOL = "before_tool_call"
    GEMINI_POST_TOOL = "after_tool_call"
    # Cursor
    CURSOR_SESSION_START = "sessionStart"
    CURSOR_PRE_TOOL = "preToolExecution"
    CURSOR_POST_TOOL = "postToolExecution"
    # Kimi
    KIMI_SESSION_START = "session_start"
    KIMI_PRE_TOOL = "before_tool"
    KIMI_POST_TOOL = "after_tool"
    # Copilot
    COPILOT_SESSION_START = "sessionStart"
    COPILOT_PRE_TOOL = "preToolExecution"
    COPILOT_POST_TOOL = "postToolExecution"
    # Pi (AI assistant)
    PI_SESSION_START = "session_start"
    PI_PRE_TOOL = "before_tool_use"
    PI_POST_TOOL = "after_tool_use"
    # OMP (Open Model Playground)
    OMP_SESSION_START = "session_start"
    OMP_PRE_TOOL = "pre_completion"
    OMP_POST_TOOL = "post_completion"
    # Antigravity (AI coding assistant)
    ANTIGRAVITY_SESSION_START = "session_start"
    ANTIGRAVITY_PRE_TOOL = "pre_action"
    ANTIGRAVITY_POST_TOOL = "post_action"
    # Generic lifecycle
    PRE_CREATE = "pre_create"
    POST_CREATE = "post_create"
    PRE_DELETE = "pre_delete"
    POST_DELETE = "post_delete"
    PRE_RESTART = "pre_restart"
    POST_RESTART = "post_restart"
    PRE_RESTORE = "pre_restore"
    POST_RESTORE = "post_restore"


# ──────────────────────────────────────────────────────────────────────────────
# Hook definitions per tool
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class HookDef:
    """Definition of a single hook for a specific tool."""
    event: HookEvent
    command: str
    timeout_secs: int = 30
    enabled: bool = True


@dataclass
class ToolHookConfig:
    """All hooks configured for a specific agent tool."""
    tool: str
    hooks: list[HookDef] = field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────────────
# Per-tool hook file paths
# ──────────────────────────────────────────────────────────────────────────────


def _claude_settings_path() -> Path:
    return Path.home() / ".claude" / "settings.json"


def _gemini_settings_path() -> Path:
    return Path.home() / ".gemini" / "settings.json"


def _codex_config_path() -> Path:
    return Path.home() / ".codex" / "config.toml"


def _cursor_hooks_path() -> Path:
    return Path.home() / ".cursor" / "hooks.json"


def _kimi_settings_path() -> Path:
    return Path.home() / ".kimi" / "settings.json"


def _copilot_settings_path() -> Path:
    return Path.home() / ".copilot" / "settings.json"


def _pi_settings_path() -> Path:
    return Path.home() / ".pi" / "settings.json"


def _omp_config_path() -> Path:
    return Path.home() / ".omp" / "config.toml"


def _antigravity_config_path() -> Path:
    return Path.home() / ".antigravity" / "hooks.json"


# ──────────────────────────────────────────────────────────────────────────────
# Hook payload (what the hook receives)
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class HookPayload:
    """Parsed hook payload from any tool."""
    tool: str
    event: str
    session_id: Optional[str] = None
    instance_name: Optional[str] = None
    hook_type: Optional[str] = None
    tool_name: Optional[str] = None
    tool_input: Optional[dict[str, Any]] = None
    tool_output: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_claude(cls, raw: dict[str, Any]) -> "HookPayload":
        return cls(
            tool="claude",
            event=raw.get("hook_type", ""),
            session_id=raw.get("session_id"),
            hook_type=raw.get("hook_type"),
            tool_name=raw.get("tool_name"),
            tool_input=raw.get("tool_input"),
            raw=raw,
        )

    @classmethod
    def from_gemini(cls, raw: dict[str, Any]) -> "HookPayload":
        return cls(
            tool="gemini",
            event=raw.get("event", ""),
            session_id=raw.get("session_id"),
            hook_type=raw.get("event"),
            tool_name=raw.get("tool_name"),
            raw=raw,
        )

    @classmethod
    def from_codex(cls, raw: dict[str, Any], hook_type: str = "") -> "HookPayload":
        return cls(
            tool="codex",
            event=hook_type,
            session_id=raw.get("session_id"),
            hook_type=hook_type,
            tool_name=raw.get("tool_name"),
            raw=raw,
        )


# ──────────────────────────────────────────────────────────────────────────────
# Hook installer
# ──────────────────────────────────────────────────────────────────────────────


class HookInstaller:
    """Installs, verifies, and removes Synapse hooks in agent config files."""

    def __init__(self, synapse_path: str = "synapse") -> None:
        self.synapse_path = synapse_path

    def install_claude_hooks(self) -> bool:
        """Install hooks into ~/.claude/settings.json for Claude Code."""
        path = _claude_settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        settings: dict[str, Any] = {}
        if path.exists():
            try:
                settings = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                settings = {}

        hooks = settings.get("hooks", [])

        # Hook command that dispatches to synapse
        hook_cmd = f"{self.synapse_path} _hook claude"

        hook_defs = [
            {"event": "sessionStart", "command": f"{hook_cmd} sessionStart"},
            {"event": "PreToolUse", "command": f"{hook_cmd} PreToolUse"},
            {"event": "PostToolUse", "command": f"{hook_cmd} PostToolUse"},
            {"event": "Stop", "command": f"{hook_cmd} Stop"},
        ]

        # Remove old synapse hooks
        hooks = [h for h in hooks if not self._is_synapse_hook(h)]

        # Add new hooks
        for hd in hook_defs:
            hooks.append({
                "event": hd["event"],
                "command": hd["command"],
            })

        settings["hooks"] = hooks
        path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
        return True

    def install_gemini_hooks(self) -> bool:
        """Install hooks into ~/.gemini/settings.json for Gemini CLI."""
        path = _gemini_settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        settings: dict[str, Any] = {}
        if path.exists():
            try:
                settings = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                settings = {}

        hook_cmd = f"{self.synapse_path} _hook gemini"

        hooks = settings.get("hooks", [])
        hooks = [h for h in hooks if not self._is_synapse_hook(h)]

        for event in ["session_start", "before_tool_call", "after_tool_call"]:
            hooks.append({
                "event": event,
                "command": f"{hook_cmd} {event}",
            })

        settings["hooks"] = hooks
        path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
        return True

    def install_codex_hooks(self) -> bool:
        """Install hooks into ~/.codex/config.toml for Codex."""
        path = _codex_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        hook_cmd = f"{self.synapse_path} _hook codex"

        content = ""
        if path.exists():
            content = path.read_text(encoding="utf-8")

        # Remove old synapse hooks section
        lines = content.split("\n")
        new_lines = []
        skip = False
        for line in lines:
            if line.strip().startswith("# synapse-hooks"):
                skip = True
            elif skip and line.strip().startswith("["):
                skip = False
            if not skip:
                new_lines.append(line)

        # Add synapse hooks
        new_lines.append("")
        new_lines.append("# synapse-hooks (auto-generated)")
        new_lines.append("[hooks]")
        new_lines.append(f'session_start = "{hook_cmd} session_start"')
        new_lines.append(f'pre_tool_call = "{hook_cmd} pre_tool_call"')
        new_lines.append(f'post_tool_call = "{hook_cmd} post_tool_call"')

        path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        return True

    def install_cursor_hooks(self) -> bool:
        """Install hooks into ~/.cursor/hooks.json for Cursor."""
        path = _cursor_hooks_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        hooks: dict[str, Any] = {}
        if path.exists():
            try:
                hooks = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                hooks = {}

        hook_cmd = f"{self.synapse_path} _hook cursor"

        # Remove old synapse hooks
        hooks = {k: v for k, v in hooks.items() if not (isinstance(v, str) and "synapse" in v)}

        hooks["sessionStart"] = f"{hook_cmd} sessionStart"
        hooks["preToolExecution"] = f"{hook_cmd} preToolExecution"
        hooks["postToolExecution"] = f"{hook_cmd} postToolExecution"

        path.write_text(json.dumps(hooks, indent=2) + "\n", encoding="utf-8")
        return True

    def install_opencode_hooks(self) -> bool:
        """Install hooks for OpenCode/Kilo."""
        path = Path.home() / ".opencode" / "hooks.json"
        path.parent.mkdir(parents=True, exist_ok=True)

        hooks: dict[str, Any] = {}
        if path.exists():
            try:
                hooks = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                hooks = {}

        hook_cmd = f"{self.synapse_path} _hook opencode"

        # Remove old synapse hooks
        hooks = {k: v for k, v in hooks.items() if not (isinstance(v, str) and "synapse" in v)}

        hooks["session_start"] = f"{hook_cmd} session_start"
        hooks["before_tool"] = f"{hook_cmd} before_tool"
        hooks["after_tool"] = f"{hook_cmd} after_tool"

        path.write_text(json.dumps(hooks, indent=2) + "\n", encoding="utf-8")
        return True

    def install_pi_hooks(self) -> bool:
        """Install hooks into ~/.pi/settings.json for Pi AI assistant."""
        path = _pi_settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        settings: dict[str, Any] = {}
        if path.exists():
            try:
                settings = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                settings = {}

        hook_cmd = f"{self.synapse_path} _hook pi"

        hooks = settings.get("hooks", [])
        hooks = [h for h in hooks if not self._is_synapse_hook(h)]

        for event in ["session_start", "before_tool_use", "after_tool_use"]:
            hooks.append({
                "event": event,
                "command": f"{hook_cmd} {event}",
            })

        settings["hooks"] = hooks
        path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
        return True

    def install_omp_hooks(self) -> bool:
        """Install hooks into ~/.omp/config.toml for OMP (Open Model Playground)."""
        path = _omp_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        hook_cmd = f"{self.synapse_path} _hook omp"

        content = ""
        if path.exists():
            content = path.read_text(encoding="utf-8")

        # Remove old synapse hooks section
        lines = content.split("\n")
        new_lines = []
        skip = False
        for line in lines:
            if line.strip().startswith("# synapse-hooks"):
                skip = True
            elif skip and line.strip().startswith("["):
                skip = False
            if not skip:
                new_lines.append(line)

        # Add synapse hooks
        new_lines.append("")
        new_lines.append("# synapse-hooks (auto-generated)")
        new_lines.append("[hooks]")
        new_lines.append(f'session_start = "{hook_cmd} session_start"')
        new_lines.append(f'pre_completion = "{hook_cmd} pre_completion"')
        new_lines.append(f'post_completion = "{hook_cmd} post_completion"')

        path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        return True

    def install_antigravity_hooks(self) -> bool:
        """Install hooks into ~/.antigravity/hooks.json for Antigravity."""
        path = _antigravity_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        hooks: dict[str, Any] = {}
        if path.exists():
            try:
                hooks = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                hooks = {}

        hook_cmd = f"{self.synapse_path} _hook antigravity"

        # Remove old synapse hooks
        hooks = {k: v for k, v in hooks.items() if not (isinstance(v, str) and "synapse" in v)}

        hooks["session_start"] = f"{hook_cmd} session_start"
        hooks["pre_action"] = f"{hook_cmd} pre_action"
        hooks["post_action"] = f"{hook_cmd} post_action"

        path.write_text(json.dumps(hooks, indent=2) + "\n", encoding="utf-8")
        return True

    def install_all_hooks(self) -> dict[str, bool]:
        """Install hooks for all known tools. Returns tool → success mapping."""
        results: dict[str, bool] = {}
        for tool, installer in [
            ("claude", self.install_claude_hooks),
            ("gemini", self.install_gemini_hooks),
            ("codex", self.install_codex_hooks),
            ("cursor", self.install_cursor_hooks),
            ("opencode", self.install_opencode_hooks),
            ("pi", self.install_pi_hooks),
            ("omp", self.install_omp_hooks),
            ("antigravity", self.install_antigravity_hooks),
        ]:
            try:
                results[tool] = installer()
            except Exception:
                results[tool] = False
        return results

    def verify_claude_hooks(self) -> bool:
        """Check if Claude hooks are installed correctly."""
        path = _claude_settings_path()
        if not path.exists():
            return False
        try:
            settings = json.loads(path.read_text(encoding="utf-8"))
            hooks = settings.get("hooks", [])
            return any(self._is_synapse_hook(h) for h in hooks)
        except (json.JSONDecodeError, OSError):
            return False

    def remove_claude_hooks(self) -> bool:
        """Remove Synapse hooks from Claude settings."""
        path = _claude_settings_path()
        if not path.exists():
            return True
        try:
            settings = json.loads(path.read_text(encoding="utf-8"))
            hooks = settings.get("hooks", [])
            settings["hooks"] = [h for h in hooks if not self._is_synapse_hook(h)]
            path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
            return True
        except (json.JSONDecodeError, OSError):
            return False

    def remove_all_hooks(self) -> dict[str, bool]:
        """Remove Synapse hooks from all known tools."""
        results: dict[str, bool] = {}
        for tool, remover in [
            ("claude", self.remove_claude_hooks),
            # Add removers for other tools as needed
        ]:
            try:
                results[tool] = remover()
            except Exception:
                results[tool] = False
        return results

    @staticmethod
    def _is_synapse_hook(hook: Any) -> bool:
        """Check if a hook entry belongs to Synapse."""
        if isinstance(hook, dict):
            cmd = hook.get("command", "")
            return "synapse" in cmd.lower()
        return False


# ──────────────────────────────────────────────────────────────────────────────
# Hook dispatcher (called by `synapse _hook <tool> <event>`)
# ──────────────────────────────────────────────────────────────────────────────


class HookDispatcher:
    """Dispatches hook events to the appropriate handler.

    When an agent fires a hook (e.g., PostToolUse), this dispatcher:
    1. Reads the hook payload from stdin
    2. Checks the DB for pending messages for this session
    3. If messages exist, outputs them as JSON (for Claude) or injects them
    4. Emits status/lifecycle events to the DB
    """

    def __init__(self) -> None:
        from ..db.database import Database
        from ..core.config import SynapseConfig
        config = SynapseConfig.load()
        self.db = Database(config.db_path)

    def dispatch(self, tool: str, event: str) -> int:
        """Handle a hook invocation. Returns exit code (0 = success)."""
        # Read payload from stdin
        try:
            raw_payload = json.loads(os.environ.get("HCOM_STDIN", "{}"))
        except (json.JSONDecodeError, TypeError):
            raw_payload = {}

        # Parse based on tool
        if tool == "claude":
            payload = HookPayload.from_claude(raw_payload)
        elif tool == "gemini":
            payload = HookPayload.from_gemini(raw_payload)
        elif tool == "codex":
            payload = HookPayload.from_codex(raw_payload, event)
        else:
            payload = HookPayload(tool=tool, event=event, raw=raw_payload)

        # Resolve session
        instance_name = payload.instance_name or os.environ.get("SYNAPSE_INSTANCE_NAME")
        session_id = payload.session_id

        if not instance_name and not session_id:
            # Try to resolve from process
            instance_name = self._resolve_instance_from_env()

        if not instance_name and not session_id:
            return 0  # No session context — nothing to do

        # Dispatch based on event type
        if event in ("PostToolUse", "after_tool_call", "post_tool_call", "postToolExecution"):
            return self._handle_post_tool_use(instance_name or session_id, payload)
        elif event in ("Stop", "session_end"):
            return self._handle_stop(instance_name or session_id, payload)
        elif event in ("sessionStart", "session_start"):
            return self._handle_session_start(instance_name or session_id, payload)
        elif event in ("PreToolUse", "before_tool_call", "pre_tool_call", "preToolExecution"):
            return self._handle_pre_tool_use(instance_name or session_id, payload)
        else:
            return 0

    def _handle_post_tool_use(self, session_id: str, payload: HookPayload) -> int:
        """PostToolUse: check for pending messages and output them."""
        from ..messaging.messenger import Messenger
        messenger = Messenger(self.db)

        # Check for pending messages
        messages = messenger.inbox(session_id, limit=5)

        if messages:
            # Format messages for injection
            formatted = self._format_messages_for_injection(messages)
            # Output to stdout (Claude reads this as tool output)
            print(json.dumps({
                "type": "synapse_messages",
                "messages": [
                    {"from": m.from_session_id, "body": m.body, "kind": m.kind}
                    for m in messages
                ],
                "formatted": formatted,
            }))
            # Mark as claimed
            messenger.claim(session_id, limit=5)

        # Log tool call event
        if payload.tool_name:
            self._log_event(session_id, "tool_call", {
                "tool": payload.tool_name,
                "tool_input": payload.tool_input,
            })

        return 0

    def _handle_pre_tool_use(self, session_id: str, payload: HookPayload) -> int:
        """PreToolUse: update status to working."""
        self.db.execute(
            "UPDATE sessions SET hook_state='working', hook_state_at=? WHERE id=? OR name=?",
            (self.db.now_ms(), session_id, session_id),
        )
        return 0

    def _handle_session_start(self, session_id: str, payload: HookPayload) -> int:
        """SessionStart: register/update the session, inject bootstrap."""
        now = self.db.now_ms()
        self.db.execute(
            "UPDATE sessions SET hook_state='idle', hook_state_at=?, status='active' WHERE id=? OR name=?",
            (now, session_id, session_id),
        )
        return 0

    def _handle_stop(self, session_id: str, payload: HookPayload) -> int:
        """Stop: mark session as done."""
        now = self.db.now_ms()
        self.db.execute(
            "UPDATE sessions SET hook_state='done', hook_state_at=?, seen_at=? WHERE id=? OR name=?",
            (now, now, session_id, session_id),
        )
        return 0

    def _resolve_instance_from_env(self) -> Optional[str]:
        """Try to resolve instance name from environment variables."""
        for key in ["SYNAPSE_INSTANCE_NAME", "HCOM_INSTANCE_NAME"]:
            val = os.environ.get(key)
            if val:
                return val
        return None

    def _format_messages_for_injection(self, messages: list) -> str:
        """Format messages as a block suitable for injection into agent context."""
        parts = ["<synapse-messages>"]
        for msg in messages:
            sender = msg.from_session_id or "system"
            body = msg.body or ""
            kind = msg.kind or "chat"
            parts.append(f"  [{kind}] from {sender}: {body}")
        parts.append("</synapse-messages>")
        return "\n".join(parts)

    def _log_event(self, session_id: str, event_type: str, data: dict) -> None:
        """Write an event to the events table."""
        import json as _json
        self.db.execute(
            "INSERT INTO events (session_id, type, data, timestamp) VALUES (?, ?, ?, ?)",
            (session_id, event_type, _json.dumps(data, default=str), self.db.now_ms()),
        )


# ──────────────────────────────────────────────────────────────────────────────
# Bootstrap primer (injected into agent system prompt on first launch)
# ──────────────────────────────────────────────────────────────────────────────


# ──────────────────────────────────────────────────────────────────────────────
# thurbox hooks.toml — lifecycle hooks for session events
# ──────────────────────────────────────────────────────────────────────────────


def _hooks_toml_path() -> Path:
    return CONFIG_DIR / "hooks.toml"


def load_hooks_toml() -> dict[str, list[dict[str, str]]]:
    """Parse ``~/.config/synapse/hooks.toml`` and return event → hook list mapping.

    Expected format:
    ```toml
    [pre_create]
    command = "echo pre-create {session_name}"

    [post_create]
    command = "echo post-create {session_name}"

    [pre_delete]
    command = "echo pre-delete {session_id}"
    ```
    """
    import tomllib

    path = _hooks_toml_path()
    if not path.exists():
        return {}

    with path.open("rb") as fh:
        raw: dict = tomllib.load(fh)

    result: dict[str, list[dict[str, str]]] = {}
    valid_events = {e.value for e in HookEvent if e.value.startswith(("pre_", "post_"))}

    for event_name, body in raw.items():
        if event_name not in valid_events:
            continue
        if isinstance(body, dict):
            hooks_list = result.setdefault(event_name, [])
            hooks_list.append({
                "command": body.get("command", ""),
                "timeout": str(body.get("timeout_secs", 30)),
            })
        elif isinstance(body, list):
            hooks_list = result.setdefault(event_name, [])
            for entry in body:
                if isinstance(entry, dict):
                    hooks_list.append({
                        "command": entry.get("command", ""),
                        "timeout": str(entry.get("timeout_secs", 30)),
                    })

    return result


def run_lifecycle_hooks(
    event: str,
    session_name: str = "",
    session_id: str = "",
    **extra: str,
) -> list[str]:
    """Run all hooks registered for *event* in hooks.toml.

    Substitutes ``{session_name}``, ``{session_id}``, and any extra kwargs
    into the command string.  Returns a list of any non-zero exit output.
    """
    hooks = load_hooks_toml()
    event_hooks = hooks.get(event, [])
    errors: list[str] = []

    for hook in event_hooks:
        cmd_template = hook.get("command", "")
        if not cmd_template:
            continue

        cmd = (
            cmd_template
            .replace("{session_name}", session_name)
            .replace("{session_id}", session_id)
        )
        for k, v in extra.items():
            cmd = cmd.replace("{ " + k + " }", v).replace("{%s}" % k, v)

        try:
            timeout = int(hook.get("timeout", "30"))
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=timeout,
            )
            if result.returncode != 0:
                errors.append(f"Hook '{event}' failed (rc={result.returncode}): {result.stderr.strip()}")
        except subprocess.TimeoutExpired:
            errors.append(f"Hook '{event}' timed out: {cmd[:80]}")
        except Exception as exc:
            errors.append(f"Hook '{event}' error: {exc}")

    return errors


def build_bootstrap_primer(instance_name: str, peers: list[dict[str, str]] | None = None) -> str:
    """Build the ~700 token bootstrap primer injected into agent system prompts.

    This teaches the agent:
    - Its Synapse instance name
    - How to send/receive messages via CLI
    - Available peer instances
    - Delivery rules
    """
    lines = [
        "# Synapse Agent Communication",
        "",
        f"You are instance **{instance_name}** in a Synapse multi-agent system.",
        "You can communicate with other agents via the Synapse message bus.",
        "",
        "## Your identity",
        f"- Instance name: `{instance_name}`",
        "- Send messages: `synapse message send --to <session_id> --body 'text'`",
        "- Check inbox: `synapse message inbox <your_session_id>`",
        "- Claim messages: `synapse message claim <your_session_id>`",
        "",
    ]

    if peers:
        lines.append("## Active peers")
        for peer in peers:
            name = peer.get("name", "?")
            agent = peer.get("agent", "?")
            status = peer.get("status", "?")
            lines.append(f"- `{name}` ({agent}) — {status}")
        lines.append("")

    lines.extend([
        "## Rules",
        "- Messages arrive via `<synapse-messages>` blocks in your context",
        "- Claim messages atomically to avoid double-processing",
        "- Broadcast to all peers by omitting --to",
        "- Use `synapse session signal <id> done` when you finish a task",
        "- Keep your work focused — coordinate via messages, not file edits",
        "",
        "## Status signals",
        "- `synapse session signal <id> working` — you started a task",
        "- `synapse session signal <id> done` — you finished a task",
        "- `synapse session signal <id> blocked` — you need help",
        "- `synapse session signal <id> idle` — you're waiting",
    ])

    return "\n".join(lines)
