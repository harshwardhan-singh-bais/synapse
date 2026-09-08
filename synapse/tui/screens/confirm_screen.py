"""
Shared confirmation modal — "Are you sure?" for destructive actions.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static


class ConfirmScreen(ModalScreen[bool]):
    """Modal confirm dialog. Dismisses with True (confirm) or False."""

    def __init__(self, title: str, body: str, confirm_label: str = "Confirm", danger: bool = True) -> None:
        super().__init__()
        self._title = title
        self._body = body
        self._confirm_label = confirm_label
        self._danger = danger

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self._title, id="dialog-title")
            yield Static(self._body, id="confirm-body")
            with Horizontal(id="dialog-buttons"):
                yield Button(
                    self._confirm_label,
                    variant="error" if self._danger else "primary",
                    id="confirm-yes",
                )
                yield Button("Cancel", id="cancel-btn")

    def on_mount(self) -> None:
        self.query_one("#confirm-yes", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm-yes":
            self.dismiss(True)
        else:
            self.dismiss(False)

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(False)
