"""
Command bar — an always-available prompt docked at the bottom of the TUI.

Accepts slash commands (like a chat-driven coding agent):

    /help                  open the help overlay
    /new <name>            create a session
    /orchestrate [goal]    launch an orchestration run
    /task <title>          create a task
    /auto <name>           create an automation (daily 09:00)
    /msg <session> <text>  send a message to a session
    /broadcast <text>      broadcast to all sessions
    /send <text>           send to the selected session
    /signal <state>        set selected session state (working/done/blocked/idle)
    /fork [name]           fork the selected session
    /attach                attach the selected session in tmux
    /refresh               refresh all panels
    /quit                  exit

Typing without a slash shows a hint; unknown commands report an error.
"""

from __future__ import annotations

import asyncio
import shlex

from textual.binding import Binding

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Input, Static

from .. import theme

# Keys the command bar must never swallow: tab switching, actions, overlays.
_PASSTHROUGH_KEYS = frozenset(
    list("1234567890nfodakmrfsx") + ["question_mark", "f5", "f6"]
)


class CommandBar(Static):
    """Bottom command line: ``❯ /command args``.

    The bar starts unfocused so single-key app bindings (1-9, n, o, ?) work
    immediately; pressing ``ctrl+p`` or clicking the input focuses it. When
    the input *is* focused, printable keys are forwarded to the app-level
    bindings via the pass-through bindings below.
    """

    BINDINGS = [
        Binding(
            "question_mark" if key == "question_mark" else key,
            f"pass_key('{key}')",
            show=False,
            priority=True,
        )
        for key in _PASSTHROUGH_KEYS
    ]

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Input(
                placeholder="  ctrl+p to type a command · /help · ? for keybindings",
                id="cmd-input",
            )

    def on_mount(self) -> None:
        # Start unfocused: keeps Textual's Input from consuming single-key
        # bindings (it strips them from the whole binding chain while focused).
        self.query_one("#cmd-input", Input).can_focus = True

    async def action_pass_key(self, key: str) -> None:
        """Run the App-level action bound to *key* (escape hatch from the input)."""
        inp = self.query_one("#cmd-input", Input)
        inp.value = ""
        bindings = self.app._bindings.key_to_bindings.get(key)  # type: ignore[attr-defined]
        if bindings:
            await self.app.run_action(bindings[0].action)  # type: ignore[attr-defined]

    # ────────────────────────────────────────────────────────────────────────
    # Command dispatch
    # ────────────────────────────────────────────────────────────────────────

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        raw = event.value.strip()
        event.input.value = ""
        if not raw:
            return

        if raw.startswith("/"):
            line = raw[1:]
        else:
            self.app.notify(
                "Commands start with /  — try /help",
                severity="information",
                timeout=3,
            )
            return

        try:
            parts = shlex.split(line)
        except ValueError:
            parts = line.split()
        if not parts:
            return

        cmd, args = parts[0].lower(), parts[1:]

        app = self.app  # type: ignore[attr-defined]
        handler = getattr(app, f"cmd_{cmd}", None)
        if handler is None:
            self.app.notify(
                f"Unknown command: /{cmd} — try /help",
                severity="warning",
                timeout=3,
            )
            return

        result = handler(*args)
        if hasattr(result, "__await__"):
            await result

    # ────────────────────────────────────────────────────────────────────────
    # Context helpers used by app-level command handlers
    # ────────────────────────────────────────────────────────────────────────

    def set_text(self, text: str) -> None:
        """Pre-fill the input (used by promptBar-style affordances)."""
        inp = self.query_one("#cmd-input", Input)
        inp.value = text
        inp.focus()

    def render_status_hint(self) -> Text:
        return Text(f" ❯ {len(self._known_commands())} commands available", style=f"dim {theme.TEXT_FAINT}")

    @staticmethod
    def _known_commands() -> list[str]:
        return [
            "help", "new", "orchestrate", "task", "auto", "msg", "broadcast",
            "send", "signal", "fork", "attach", "refresh", "quit",
        ]
