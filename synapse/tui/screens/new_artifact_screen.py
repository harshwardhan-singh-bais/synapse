"""
Modal screen for writing a knowledge artifact from the TUI.

Collects key, name and content; returns a dict via ``dismiss``.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, TextArea


class NewArtifactScreen(ModalScreen[dict | None]):
    """Modal dialog for writing a knowledge artifact."""

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("🧠 New Artifact", id="dialog-title")

            yield Label("Key")
            yield Input(placeholder="e.g. design/auth-flow", id="key-input")

            yield Label("Name  (optional)")
            yield Input(placeholder="Human-readable name", id="name-input")

            yield Label("Content")
            yield TextArea(
                "",
                id="content-input",
                show_line_numbers=False,
                soft_wrap=True,
                classes="field-goal",
            )

            with Horizontal(id="dialog-buttons"):
                yield Button("✓  Write", variant="primary", id="create-btn")
                yield Button("✗  Cancel", id="cancel-btn")

    def on_mount(self) -> None:
        self.query_one("#key-input", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
            self.dismiss(None)
            return
        if event.button.id == "create-btn":
            key = self.query_one("#key-input", Input).value.strip()
            if not key:
                self.query_one("#key-input", Input).focus()
                return
            self.dismiss(
                {
                    "key": key,
                    "name": self.query_one("#name-input", Input).value.strip() or None,
                    "content": self.query_one("#content-input", TextArea).text,
                }
            )

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)