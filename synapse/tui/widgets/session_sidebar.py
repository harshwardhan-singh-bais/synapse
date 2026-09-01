"""
Session sidebar — live list of all agent sessions with status indicators.
Updates every 2 seconds from the DB.
"""
from __future__ import annotations

import time
from typing import Optional

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widgets import Label, ListItem, ListView, Static
from rich.text import Text

# Status icon + style pairs
STATUS_ICONS: dict[str, tuple[str, str]] = {
    "idle":        ("○", "dim"),
    "working":     ("●", "bright_green"),
    "blocked":     ("◉", "bright_red"),
    "done":        ("✓", "bright_cyan"),
    "error":       ("✗", "bright_red"),
    "unreachable": ("?", "yellow"),
    "active":      ("●", "bright_green"),
}

_DEFAULT_ICON = ("·", "dim")


def _status_icon(status: Optional[str]) -> tuple[str, str]:
    if status is None:
        return _DEFAULT_ICON
    return STATUS_ICONS.get(status.lower(), _DEFAULT_ICON)


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
            yield Label("⚡ SESSIONS", classes="sidebar-title")
            if not self.sessions:
                yield Label(
                    " No sessions yet\n Press [bold cyan]n[/] to create one",
                    classes="sidebar-empty",
                )
            else:
                with ListView(id="session-list"):
                    for s in self.sessions:
                        icon, style = _status_icon(s.status or s.hook_state)
                        age = _age_str(s.created_at)

                        text = Text()
                        text.append(f" {icon} ", style=style)
                        text.append(
                            f"{s.name[:16]:<16}",
                            style="bold white" if s.id == self.selected_session_id else "white",
                        )
                        text.append(f" {age:>3}", style="dim")

                        agent_label = (s.agent or "?")[:8]
                        text.append(f"\n   {agent_label}", style="dim cyan")
                        if s.cwd:
                            short_cwd = s.cwd.split("/")[-1] or s.cwd.split("\\")[-1]
                            text.append(f"  {short_cwd[:12]}", style="dim")

                        item = ListItem(Label(text), id=f"sess-{s.id}")
                        if s.id == self.selected_session_id:
                            item.add_class("selected-item")
                        yield item

    def on_mount(self) -> None:
        self.refresh_sessions()
        self.set_interval(2.0, self.refresh_sessions)

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
