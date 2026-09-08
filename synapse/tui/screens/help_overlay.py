"""
Help overlay — every keybinding and slash command on one screen.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Label, Static

from .. import theme

_KEY_BINDINGS: list[tuple[str, str]] = [
    ("1-9",        "switch panel (Overview, Sessions, Runs, Mailbox, Tasks, Autos, Knowledge, Relay, Activity)"),
    ("0",          "System panel (config, agents, plugins, scripts)"),
    ("n",          "new session"),
    ("o",          "launch orchestration"),
    ("t",          "new task"),
    ("a",          "new automation"),
    ("k",          "new knowledge artifact"),
    ("m",          "compose message to selected session"),
    ("d",          "delete selected session (asks to confirm)"),
    ("r",          "restart selected session"),
    ("f",          "fork selected session"),
    ("s",          "signal selected session (working/done/blocked/idle)"),
    ("x",          "attach selected session in tmux"),
    ("F5",         "refresh all panels"),
    ("F6",         "toggle performance HUD"),
    ("?",          "this help"),
    ("q",          "quit"),
]

_COMMANDS: list[tuple[str, str]] = [
    ("/help",                    "show this help"),
    ("/new <name>",              "create a session"),
    ("/orchestrate [goal]",      "launch an orchestration run"),
    ("/task <title>",            "create a task"),
    ("/auto <name>",             "create a daily automation"),
    ("/msg <session> <text>",    "message a session by name or id"),
    ("/send <text>",             "message the selected session"),
    ("/broadcast <text>",        "broadcast to every session"),
    ("/signal <state>",          "set selected session state"),
    ("/fork [name]",             "fork the selected session"),
    ("/attach",                  "attach the selected session in tmux"),
    ("/refresh",                 "refresh all panels"),
    ("/quit",                    "exit Synapse"),
]


class HelpOverlay(Screen[None]):
    """Full-screen help overlay; dismiss with escape, q, or ?."""

    BINDINGS = [
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
        ("question_mark", "close", "Close"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="help-panel"):
            yield Label("  Help — Synapse", id="help-title")
            yield Static(self._render_help(), id="help-content")
            yield Label("  press [bold #e89173]esc[/] to close", id="help-hint")

    @staticmethod
    def _render_help() -> Text:
        text = Text()

        text.append("\n  KEYBINDINGS\n", style=f"bold {theme.ACCENT_HI}")
        text.append("  " + "─" * 66 + "\n", style=f"dim {theme.EDGE}")
        for key, desc in _KEY_BINDINGS:
            text.append(f"  {key:<14}", style=f"bold {theme.CYAN}")
            text.append(f"{desc}\n", style=f"dim {theme.TEXT_DIM}")

        text.append("\n  SLASH COMMANDS\n", style=f"bold {theme.ACCENT_HI}")
        text.append("  " + "─" * 66 + "\n", style=f"dim {theme.EDGE}")
        for cmd, desc in _COMMANDS:
            text.append(f"  {cmd:<26}", style=f"bold {theme.GREEN}")
            text.append(f"{desc}\n", style=f"dim {theme.TEXT_DIM}")

        text.append("\n  TIP  ", style=f"bold {theme.ACCENT}")
        text.append(
            "select a session in the sidebar to drive every panel from it.\n",
            style=f"dim {theme.TEXT_DIM}",
        )
        return text

    def action_close(self) -> None:
        self.app.pop_screen()  # type: ignore[attr-defined]
