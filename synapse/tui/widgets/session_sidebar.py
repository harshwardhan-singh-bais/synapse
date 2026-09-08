"""
Session sidebar — live list of all agent sessions with status pills.
Updates every 2 seconds from the DB.
"""

from __future__ import annotations

import time
from typing import Optional

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widgets import Label, ListItem, ListView, Static

from .. import theme

# Status glyphs + themed colors
STATUS_GLYPHS: dict[str, str] = {
    "idle":        "○",
    "working":     "●",
    "active":      "●",
    "blocked":     "◉",
    "done":        "✓",
    "error":       "✗",
    "unreachable": "?",
}

_DEFAULT_GLYPH = "·"


def _status_glyph(status: Optional[str]) -> str:
    if status is None:
        return _DEFAULT_GLYPH
    return STATUS_GLYPHS.get(status.lower(), _DEFAULT_GLYPH)


def _age_str(created_at_ms: Optional[int]) -> str:
    """Return a short human age string, e.g. '3h', '2d'."""
    if created_at_ms is None:
        return ""
    delta = int(time.time()) - created_at_ms // 1000
    if delta < 60:
        return f"{delta}s"
    if delta < 3600:
        return f"{delta // 60}m"
    if delta < 86400:
        return f"{delta // 3600}h"
    return f"{delta // 86400}d"


class SessionSidebar(Static):
    """Left sidebar showing all sessions with live status indicators."""

    # Reactive list of SessionInfo objects loaded from DB
    sessions: reactive[list] = reactive([], recompose=True)
    selected_session_id: reactive[Optional[str]] = reactive(None)

    # Posted when the user selects a session
    class SessionSelected:
        def __init__(self, session_id: str) -> None:
            self.session_id = session_id

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(id="sidebar-title", classes="sidebar-title")
            if not self.sessions:
                yield Label(
                    "[dim]  no sessions yet…\n  press [/][bold #e89173]n[/][dim] to mint one[/]",
                    classes="sidebar-empty",
                )
            else:
                with ListView(id="session-list"):
                    for s in self.sessions:
                        yield self._build_item(s)

    def _build_item(self, s) -> ListItem:
        status = (s.status or s.hook_state or "idle").lower()
        glyph = _status_glyph(status)
        fg = theme.STATUS_FG.get(status, theme.TEXT_DIM)
        bg = theme.STATUS_BG.get(status, "#18151f")
        age = _age_str(s.created_at)

        text = Text()
        # ── status glyph + name + age ───────────────────────────────────────
        text.append(f" {glyph} ", style=fg)
        name_style = "bold #e8e4dc" if s.id == self.selected_session_id else "#e8e4dc"
        text.append(f"{s.name[:14]:<14}", style=name_style)
        text.append(f"{age:>4} ", style=f"dim {theme.TEXT_FAINT}")
        text.append("\n")

        # ── status pill ─────────────────────────────────────────────────────
        text.append("   ")
        text.append(
            f"{status[:11]:^11}",
            style=f"bold {fg} on {bg}",
        )
        # ── agent chip ──────────────────────────────────────────────────────
        agent = (s.agent or "?")[:8]
        color = theme.agent_color(agent)
        text.append(f" {agent:<8}", style=f"bold {color}")
        # ── cwd tail ────────────────────────────────────────────────────────
        if s.cwd:
            short_cwd = s.cwd.split("/")[-1] or s.cwd.split("\\")[-1]
            text.append(f" {short_cwd[:10]}", style=f"dim {theme.TEXT_FAINT}")

        item = ListItem(Label(text), id=f"sess-{s.id}")
        if s.id == self.selected_session_id:
            item.add_class("selected-item")
        return item

    def on_mount(self) -> None:
        self._update_title()
        self.refresh_sessions()
        self.set_interval(2.0, self.refresh_sessions)

    def _update_title(self) -> None:
        title = self.query_one("#sidebar-title", Label)
        text = Text()
        text.append(" ⚑ SESSIONS", style=f"bold {theme.TEXT_DIM}")
        text.append(f"  ({len(self.sessions)})", style=f"dim {theme.TEXT_FAINT}")
        title.update(text)

    def refresh_sessions(self) -> None:
        """Pull sessions from the DB and update the reactive list."""
        try:
            db = self.app.db  # type: ignore[attr-defined]
            rows = db.fetchall(
                "SELECT * FROM sessions WHERE deleted_at IS NULL ORDER BY display_order ASC, created_at DESC"
            )
            from ...session.models import SessionInfo
            self.sessions = [SessionInfo.model_validate(dict(r)) for r in rows]
        except Exception:
            pass  # DB might not be ready yet

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Bubble a SessionSelected message when the user picks a session."""
        item_id: str = event.item.id or ""
        if item_id.startswith("sess-"):
            session_id = item_id[5:]
            self.selected_session_id = session_id
            # Post to app
            self.app.on_session_selected(session_id)  # type: ignore[attr-defined]