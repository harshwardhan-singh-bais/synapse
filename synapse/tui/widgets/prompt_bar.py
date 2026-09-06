"""
Claude-Code-style bottom bar.

Left:  ``❯`` prompt with a blinking block cursor + quick-key hints.
Right: live status chips (sessions, runs, agent, effort, clock).
"""

from __future__ import annotations

import time
from pathlib import Path

from rich.text import Text
from textual.widgets import Static

from ..ascii import spinner
from .. import theme


class PromptBar(Static):
    """Living status / prompt bar docked at the bottom of the screen."""

    def __init__(
        self,
        db_path: Path,
        default_agent: str = "claude",
        effort: str = "standard",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._db_path = db_path
        self._default_agent = default_agent
        self._effort = effort
        self._tick = 0
        self._sessions = 0
        self._runs = 0
        self._cursor_on = True

    def on_mount(self) -> None:
        self._slow_tick()
        self._blink_tick()
        self.set_interval(1.0, self._slow_tick)
        self.set_interval(0.55, self._blink_tick)

    def _slow_tick(self) -> None:
        try:
            db = self.app.db  # type: ignore[attr-defined]
            row = db.fetchone("SELECT COUNT(*) c FROM sessions WHERE deleted_at IS NULL")
            self._sessions = row["c"] if row else 0
            row = db.fetchone("SELECT COUNT(*) c FROM runs WHERE status = 'running'")
            self._runs = row["c"] if row else 0
        except Exception:
            self._sessions, self._runs = 0, 0

    def _blink_tick(self) -> None:
        self._cursor_on = not self._cursor_on
        self._tick += 1
        self.refresh()

    def render(self) -> Text:
        width = max(self.size.width, 40)
        out = Text()

        # ── Prompt zone ─────────────────────────────────────────────────────
        out.append(" ❯", style=f"bold {theme.ACCENT_HI}")
        if self._cursor_on:
            out.append("█", style=f"bold {theme.ACCENT}")
        else:
            out.append("░", style=f"dim {theme.TEXT_FAINT}")
        out.append(
            "  /new  /runs  /mail  /orch   ",
            style=f"bold {theme.TEXT_DIM}",
        )

        # ── Right status zone ───────────────────────────────────────────────
        right = Text()
        right.append(f" {spinner('braille', self._tick)} ", style=f"bold {theme.ACCENT_HI}")
        right.append("SYN·APSE", style=f"bold {theme.TEXT}")
        right.append(f"  ⚑ {self._sessions}", style=f"bold {theme.CYAN}")
        right.append(f"  ⟳ {self._runs}", style=f"bold {theme.YELLOW}")
        right.append(
            f"  {self._default_agent}",
            style=f"bold {theme.agent_color(self._default_agent)}",
        )
        right.append(f"  {self._effort}", style=f"bold {theme.PURPLE}")
        right.append(f"  {time.strftime('%H:%M:%S')}", style=f"bold {theme.TEXT_DIM}")

        pad = max(0, width - out.cell_len - right.cell_len)
        out.append(" " * pad)
        out.append_text(right)
        return out