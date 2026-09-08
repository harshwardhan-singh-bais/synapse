"""
Synapse header — a professional single-line top bar.

Left:   terracotta brand chip + SYNAPSE wordmark + tagline
Right:  live status dot, session / run counters, clock
"""

from __future__ import annotations

import time
from pathlib import Path

from rich.text import Text
from textual.widgets import Static

from .. import theme


class SynapseHeader(Static):
    """Calm, information-dense header: logo, live counters and a clock."""

    def __init__(self, db_path: Path, default_agent: str = "claude", **kwargs) -> None:
        super().__init__(**kwargs)
        self._db_path = db_path
        self._default_agent = default_agent
        self._sessions = 0
        self._runs = 0
        self._active = 0

    def on_mount(self) -> None:
        self._slow_tick()
        self.set_interval(1.0, self._slow_tick)

    def _slow_tick(self) -> None:
        try:
            db = self.app.db  # type: ignore[attr-defined]
            row = db.fetchone("SELECT COUNT(*) c FROM sessions WHERE deleted_at IS NULL")
            self._sessions = row["c"] if row else 0
            row = db.fetchone(
                "SELECT COUNT(*) c FROM sessions WHERE deleted_at IS NULL "
                "AND status IN ('active','working')"
            )
            self._active = row["c"] if row else 0
            row = db.fetchone("SELECT COUNT(*) c FROM runs WHERE status = 'running'")
            self._runs = row["c"] if row else 0
        except Exception:
            self._sessions, self._runs, self._active = 0, 0, 0
        self.refresh()

    def render(self) -> Text:
        width = max(self.size.width, 40)
        out = Text()

        # ── Brand ───────────────────────────────────────────────────────
        out.append(" ⚡ ", style=f"bold {theme.ON_ACCENT} on {theme.ACCENT}")
        out.append(" SYNAPSE", style=f"bold {theme.TEXT}")
        out.append("  unified agent orchestration", style=f"dim {theme.TEXT_FAINT}")

        # ── Right cluster ───────────────────────────────────────────────
        live_color = theme.GREEN if self._active or self._runs else theme.TEXT_FAINT
        right = Text()
        right.append("● ", style=f"bold {live_color}")
        right.append("live", style=f"dim {theme.TEXT_FAINT}")
        right.append(f"  ⚑ {self._active}/{self._sessions}", style=f"bold {theme.CYAN}")
        right.append(f"  ⟳ {self._runs}", style=f"bold {theme.GREEN}")
        right.append(f"  {time.strftime('%H:%M')}", style=f"bold {theme.TEXT_DIM}")

        pad = max(0, width - out.cell_len - right.cell_len)
        out.append(" " * pad)
        out.append_text(right)
        return out
