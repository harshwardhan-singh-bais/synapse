"""
Modal screen for launching an orchestration run from the TUI.

Mode: goal | test | improve | resume. Goal text, repo path, effort and
team are collected and returned as a dict via ``dismiss``.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, TextArea

_MODE_OPTIONS = [
    ("goal", "goal"),
    ("test", "test"),
    ("improve", "improve"),
    ("resume", "resume"),
]

_EFFORT_OPTIONS = [
    ("standard", "standard"),
    ("low", "low"),
    ("high", "high"),
    ("max", "max"),
]

_TEAM_OPTIONS = [
    ("full", "full"),
    ("quick", "quick"),
    ("test", "test"),
]


class OrchestrateScreen(ModalScreen[dict | None]):
    """Modal dialog for launching an orchestration run."""

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("⟳ Launch Orchestration", id="dialog-title")

            yield Label("Mode")
            yield Select(_MODE_OPTIONS, value="goal", id="mode-select")

            yield Label("Goal")
            yield TextArea(
                "Achieve the goal and verify the work.",
                id="goal-input",
                show_line_numbers=False,
                soft_wrap=True,
                classes="field-goal",
            )

            yield Label("Repository Path")
            yield Input(
                placeholder="/path/to/repo  (defaults to CWD)",
                id="repo-input",
            )

            yield Label("Effort")
            yield Select(_EFFORT_OPTIONS, value="standard", id="effort-select")

            yield Label("Team")
            yield Select(_TEAM_OPTIONS, value="full", id="team-select")

            with Horizontal(id="dialog-buttons"):
                yield Button("✓  Launch", variant="primary", id="create-btn")
                yield Button("✗  Cancel", id="cancel-btn")

    def on_mount(self) -> None:
        self.query_one("#goal-input", TextArea).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
            self.dismiss(None)
            return
        if event.button.id == "create-btn":
            mode = self.query_one("#mode-select", Select).value
            goal = self.query_one("#goal-input", TextArea).text.strip()
            repo = self.query_one("#repo-input", Input).value.strip()
            effort = self.query_one("#effort-select", Select).value
            team = self.query_one("#team-select", Select).value

            mode = str(mode) if mode is not Select.BLANK else "goal"
            effort = str(effort) if effort is not Select.BLANK else "standard"
            team = str(team) if team is not Select.BLANK else "full"

            if mode in ("goal",) and not goal:
                self.query_one("#goal-input", TextArea).focus()
                return

            self.dismiss(
                {
                    "mode": mode,
                    "goal": goal,
                    "repo_path": repo or None,
                    "effort": effort,
                    "team": team,
                }
            )

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)