"""
Modal screen for creating a new task from the TUI.

Collects title, description, optional action (send/spawn/exec) and returns
a dict via ``dismiss``.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, TextArea

_ACTION_OPTIONS = [
    ("none", "none"),
    ("send (prompt a session)", "send"),
    ("spawn (new session)", "spawn"),
    ("exec (shell command)", "exec"),
]


class NewTaskScreen(ModalScreen[dict | None]):
    """Modal dialog for creating a task."""

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("＋ New Task", id="dialog-title")

            yield Label("Title")
            yield Input(placeholder="e.g. refactor auth module", id="title-input")

            yield Label("Description / prompt")
            yield TextArea(
                "",
                id="desc-input",
                show_line_numbers=False,
                soft_wrap=True,
                classes="field-goal",
            )

            yield Label("Action")
            yield Select(_ACTION_OPTIONS, value="none", id="action-select")

            yield Label("Target Session  (for action=send)")
            yield Input(placeholder="session id or name", id="session-input")

            yield Label("Repo Path  (for action=spawn)")
            yield Input(placeholder="/path/to/repo", id="repo-input")

            yield Label("Agent  (for action=spawn)")
            yield Input(placeholder="claude", id="agent-input")

            yield Label("Branch  (for action=spawn)")
            yield Input(placeholder="feature/x  — optional", id="branch-input")

            yield Label("Command  (for action=exec)")
            yield Input(placeholder="e.g. pytest -q", id="command-input")

            with Horizontal(id="dialog-buttons"):
                yield Button("✓  Create", variant="primary", id="create-btn")
                yield Button("✗  Cancel", id="cancel-btn")

    def on_mount(self) -> None:
        self.query_one("#title-input", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
            self.dismiss(None)
            return
        if event.button.id == "create-btn":
            title = self.query_one("#title-input", Input).value.strip()
            if not title:
                self.query_one("#title-input", Input).focus()
                return

            action = self.query_one("#action-select", Select).value
            action = str(action) if action is not Select.BLANK else "none"

            self.dismiss(
                {
                    "title": title,
                    "description": self.query_one("#desc-input", TextArea).text.strip() or None,
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