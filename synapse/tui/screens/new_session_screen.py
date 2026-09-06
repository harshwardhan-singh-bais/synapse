"""
Modal screen for creating a new agent session.
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select


_AGENT_OPTIONS = [
    ("claude", "claude"),
    ("cursor", "cursor"),
    ("codex", "codex"),
    ("gemini-cli", "gemini-cli"),
]


class NewSessionScreen(ModalScreen[dict | None]):
    """Modal dialog for creating a new agent session."""

    DEFAULT_CSS = """
    NewSessionScreen {
        align: center middle;
    }

    #dialog {
        background: #15131c;
        border: double #d97757;
        padding: 2 3;
        width: 64;
        height: auto;
        max-height: 80%;
    }

    #dialog-title {
        color: #ffd166;
        text-style: bold;
        text-align: center;
        margin-bottom: 1;
        padding-bottom: 1;
        border-bottom: tall #262230;
    }

    #dialog Label {
        color: #c792ea;
        margin-top: 1;
    }

    #dialog Input {
        margin-top: 0;
        background: #09080d;
        border: solid #262230;
        color: #efe9e0;
    }

    #dialog Input:focus {
        border: tall #d97757;
    }

    #dialog Select {
        margin-top: 0;
        background: #09080d;
        border: solid #262230;
    }

    #dialog-buttons {
        margin-top: 2;
        align: right middle;
    }

    #create-btn {
        background: #d97757;
        border: none;
        color: #1c0f07;
        margin-right: 1;
    }

    #create-btn:hover {
        background: #ff8a5c;
    }

    #cancel-btn {
        background: #241d28;
        border: solid #3b3350;
        color: #968ba2;
    }

    #cancel-btn:hover {
        background: #3b3350;
        border: solid #967ba2;
    }

    .field-hint {
        color: #5f566c;
        text-style: italic;
        margin-top: 0;
        margin-bottom: 0;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("[bold #ffd166]⚡ New Agent Session[/]", id="dialog-title")

            yield Label("Session Name")
            yield Input(
                placeholder="e.g. feature-auth",
                id="name-input",
            )

            yield Label("Repository Path")
            yield Input(
                placeholder="/path/to/repo  (leave blank to use CWD)",
                id="repo-input",
            )

            yield Label("Agent")
            yield Select(
                _AGENT_OPTIONS,
                value="claude",
                id="agent-select",
            )

            yield Label("Worktree Branch  (optional)")
            yield Input(
                placeholder="e.g. feature/auth  — leave blank for none",
                id="branch-input",
            )

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
            repo_path = self.query_one("#repo-input", Input).value.strip()
            agent_select = self.query_one("#agent-select", Select)
            branch = self.query_one("#branch-input", Input).value.strip()

            if not name:
                self.query_one("#name-input", Input).focus()
                return

            agent_value = agent_select.value
            if agent_value is Select.BLANK:
                agent_value = "claude"

            self.dismiss(
                {
                    "name": name,
                    "repo_path": repo_path or None,
                    "agent": str(agent_value),
                    "worktree_branch": branch or None,
                }
            )

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)
