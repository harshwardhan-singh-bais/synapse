"""
Synapse header — a Claude-Code-style top bar.

Three zones:
- left:   ``⚡`` brand chip + rainbow SYN▪APSE wordmark + tagline
- center: breathing separator
- right:  live ASCII spinner + session/run counters + clock
"""

from __future__ import annotations

import time
from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.widgets import Static

from ..ascii import gradient_rule, spinner
from .. import theme


class SynapseHeader(Static):
    """Living header: logo, status spinner, counters and a clock."""

    def __init__(self, db_path: Path, default_agent: str = "claude", **kwargs) -> None:
        super().__init__(**kwargs)
        self._db_path = db_path
        self._default_agent = default_agent
        self._tick = 0
        self._sessions = 0
        self._runs = 0

    def on_mount(self) -> None:
        self._slow_tick()
        self.set_interval(1.0, self._slow_tick)
        self.set_interval(0.16, self._spin_tick)

    def _slow_tick(self) -> None:
        try:
            db = self.app.db  # type: ignore[attr-defined]
            row = db.fetchone("SELECT COUNT(*) c FROM sessions WHERE deleted_at IS NULL")
            self._sessions = row["c"] if row else 0
            row = db.fetchone("SELECT COUNT(*) c FROM runs WHERE status = 'running'")
            self._runs = row["c"] if row else 0
        except Exception:
            self._sessions, self._runs = 0, 0

    def _spin_tick(self) -> None:
        self._tick += 1
        self.refresh()

    def render(self) -> Text:
        tick = self._tick
        width = max(self.size.width, 40)
        out = Text()

        # ── Line 1: brand chip + wordmark + tagline ─────────────────────────
        line1 = Text()
        line1.append(" ⚡ ", style=f"bold {theme.ON_ACCENT} on {theme.ACCENT}")
        line1.append_text(_wordmark_gradient())
        line1.append("  unified agent orchestration", style=f"dim {theme.TEXT_FAINT}")

        # ── Right cluster (line 1) ──────────────────────────────────────────
        clock = time.strftime("%H:%M:%S")
        right = Text()
        right.append(f" {spinner('braille', tick)} ", style=f"bold {theme.ACCENT_HI}")
        right.append("LIVE", style=f"bold {theme.GREEN}")
        right.append(f"  ⚑ {self._sessions}", style=f"bold {theme.CYAN}")
        right.append(f"  ⟳ {self._runs}", style=f"bold {theme.YELLOW}")
        right.append(f"  {clock}", style=f"bold {theme.TEXT_DIM}")

        pad = max(0, width - line1.cell_len - right.cell_len)
        line1.append(" " * pad)
        line1.append_text(right)

        # ── Line 2: gradient rule ───────────────────────────────────────────
        rule = Text()
        sw = max(width - 2, 10)
        stops = theme.GRADIENT_LOGO
        for idx in range(sw):
            color = stops[int(idx / max(sw - 1, 1) * (len(stops) - 1))]
            rule.append("─", style=f"dim {color}")

        out.append_text(line1)
        out.append("\n")
        out.append_text(rule)
        return out