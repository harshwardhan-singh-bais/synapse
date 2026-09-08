"""
Activity feed — live stream of every recorded event across all sessions.

Shows messages, status transitions, file edits, tool calls and lifecycle
events with per-type colour coding, newest first.
"""

from __future__ import annotations

import json
import time

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import ScrollableContainer, Vertical
from textual.widgets import Label, Static

from .. import theme

EVENT_STYLES = {
    "message":   ("💬", theme.PINK),
    "status":    ("◉", theme.YELLOW),
    "life":      ("●", theme.CYAN),
    "file_edit": ("✎", theme.YELLOW),
    "tool_call": ("⚙", theme.CYAN),
    "collision": ("⚠", theme.RED),
}


def _ts_str(ms: int | None) -> str:
    if not ms:
        return "?"
    return time.strftime("%H:%M:%S", time.localtime(ms // 1000))


class ActivityFeed(Static):
    """Event-by-event activity stream."""

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("  📡 ACTIVITY", id="activity-title", classes="dashboard-title")
            with ScrollableContainer(id="activity-scroll"):
                yield Static(id="activity-content")

    def on_mount(self) -> None:
        self.refresh_feed()
        self.set_interval(2.0, self.refresh_feed)

    def refresh_feed(self) -> None:
        if not self.visible:
            return
        try:
            db = self.app.db  # type: ignore[attr-defined]
            rows = db.fetchall(
                "SELECT * FROM events ORDER BY timestamp DESC LIMIT 200"
            )
            content = self.query_one("#activity-content", Static)

            text = Text()
            if not rows:
                text.append("\n  No activity recorded yet.\n", style="dim italic")
                content.update(text)
                return

            for ev in rows:
                ts = _ts_str(ev["timestamp"])
                ev_type = ev["type"] or "?"
                glyph, color = EVENT_STYLES.get(ev_type, ("·", theme.TEXT_DIM))
                sid = (ev["session_id"] or "system")[:10]

                text.append(f"  [{ts}]", style=f"dim {theme.TEXT_FAINT}")
                text.append(f" {glyph} ", style=f"bold {color}")
                text.append(f"{sid:<10}", style=f"dim {theme.CYAN}")
                text.append(f"{ev_type:<11}", style=f"bold {color}")

                try:
                    data = json.loads(ev["data"] or "{}")
                except Exception:
                    data = {}

                if ev_type == "message":
                    summary = (data.get("body") or "")[:46]
                elif ev_type == "file_edit":
                    summary = (data.get("file_path") or "")[:46]
                elif ev_type == "tool_call":
                    summary = (data.get("tool") or "")[:46]
                elif ev_type == "status":
                    summary = (data.get("status") or data.get("hook_state") or "")[:46]
                else:
                    summary = str(data)[:46] if data else ""

                text.append(f" {summary}\n", style=f"dim {theme.TEXT_DIM}")

            content.update(text)
        except Exception:
            pass