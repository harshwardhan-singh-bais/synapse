"""
Modal screen for creating a scheduled automation from the TUI.

Collects name, trigger preset or custom cron/ISO, action kind and related
fields; returns a dict via ``dismiss``.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, TextArea

_TRIGGER_OPTIONS = [
    ("hourly  (0 * * * *)", "hourly"),
    ("daily  (0 9 * * *)", "daily"),
    ("weekly  (0 9 * * 1)", "weekly"),
    ("midnight  (0 0 * * *)", "midnight"),
    ("every 5 minutes", "every5m"),
    ("every 15 minutes", "every15m"),
    ("every 30 minutes", "every30m"),
    ("custom…", "custom"),
]

_ACTION_OPTIONS = [
    ("none", "none"),
    ("send (prompt a session)", "send"),
    ("spawn (new session)", "spawn"),
    ("exec (shell command)", "exec"),
]


class NewAutomationScreen(ModalScreen[dict | None]):
    """Modal dialog for creating an automation."""

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("⏱ New Automation", id="dialog-title")

            yield Label("Name")
            yield Input(placeholder="e.g. morning-sync", id="name-input")

            yield Label("Trigger")
            yield Select(_TRIGGER_OPTIONS, value="daily", id="trigger-select")
            yield Label("Custom trigger  (cron or ISO datetime — only for custom)", classes="field-hint")
            yield Input(placeholder="e.g. 0 6 * * 1-5  or  2026-01-01T09:00:00", id="trigger-input")

            yield Label("Prompt")
            yield TextArea(
                "",
                id="prompt-input",
                show_line_numbers=False,
                soft_wrap=True,
                classes="field-goal",
            )

            yield Label("Action")
            yield Select(_ACTION_OPTIONS, value="send", id="action-select")

            yield Label("Target Session  (for action=send)")
            yield Input(placeholder="session id or name", id="session-input")

            yield Label("Repo Path  (for action=spawn)")
            yield Input(placeholder="/path/to/repo", id="repo-input")

            yield Label("Agent  (for action=spawn)")
            yield Input(placeholder="claude", id="agent-input")

            yield Label("Branch  (for action=spawn)")
            yield Input(placeholder="feature/x  — optional", id="branch-input")

            yield Label("Command  (for action=exec)")
            yield Input(placeholder="e.g. make deploy", id="command-input")

            with Horizontal(id="dialog-buttons"):
                yield Button("✓  Create", variant="primary", id="create-btn")
                yield Button("✗  Cancel", id="cancel-btn")

    def on_mount(self) -> None:
        self.query_one("#name-input", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
            self.dismiss(None)
            return
        if event.button.id == "create-btn":
            name = self.query_one("#name-input", Input).value.strip()
            if not name:
                self.query_one("#name-input", Input).focus()
                return

            trigger_sel = self.query_one("#trigger-select", Select).value
            trigger_sel = str(trigger_sel) if trigger_sel is not Select.BLANK else "daily"
            custom = self.query_one("#trigger-input", Input).value.strip()
            trigger = custom if trigger_sel == "custom" and custom else trigger_sel

            action = self.query_one("#action-select", Select).value
            action = str(action) if action is not Select.BLANK else "none"

            self.dismiss(
                {
                    "name": name,
                    "trigger": trigger,
                    "prompt": self.query_one("#prompt-input", TextArea).text.strip() or None,
                    "action_kind": None if action == "none" else action,
                    "target_session": self.query_one("#session-input", Input).value.strip() or None,
                    "repo_path": self.query_one("#repo-input", Input).value.strip() or None,
                    "agent": self.query_one("#agent-input", Input).value.strip() or None,
                    "branch": self.query_one("#branch-input", Input).value.strip() or None,
                    "command": self.query_one("#command-input", Input).value.strip() or None,
                }
            )

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)