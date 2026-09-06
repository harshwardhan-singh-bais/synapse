"""
Agent mailbox — view and compose inter-session messages.
Shows thread view with collision warnings highlighted in red/orange.
"""
from __future__ import annotations

import time
from typing import Optional

from textual.app import ComposeResult
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.reactive import reactive
from textual.widgets import Button, DataTable, Input, Label, Static
from rich.text import Text

from ..ascii import spinner
from .. import theme


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

KIND_GLYPHS: dict[str, str] = {
    "chat":      "💬",
    "questions": "❓",
    "plan":      "📋",
    "result":    "📊",
    "status":    "📡",
    "collision": "⚠️ ",
}

KIND_STYLES: dict[str, str] = {
    "chat":      theme.PINK,
    "questions": theme.YELLOW,
    "plan":      theme.CYAN,
    "result":    theme.GREEN,
    "status":    theme.ACCENT_HI,
    "collision": theme.RED,
}


def _ts_str(ms: Optional[int]) -> str:
    if ms is None:
        return "?"
    return time.strftime("%H:%M:%S", time.localtime(ms // 1000))


# ─────────────────────────────────────────────────────────────────────────────
# Mailbox widget
# ─────────────────────────────────────────────────────────────────────────────

class AgentMailbox(Static):
    """
    Mailbox panel showing:
    - Inbox for the selected session
    - Thread view with collision alerts highlighted
    - Compose area to send messages
    """

    session_id: reactive[Optional[str]] = reactive(None)

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("📬 AGENT MAILBOX", id="mailbox-title", classes="dashboard-title")
            with Horizontal(id="mailbox-top"):
                # Left: inbox list
                with Vertical(id="inbox-panel"):
                    yield Label("  Inbox", classes="panel-subtitle")
                    yield Static(id="inbox-content")
                # Right: thread view
                with ScrollableContainer(id="thread-panel"):
                    yield Label("  Thread View", classes="panel-subtitle")
                    yield Static(id="thread-content")
            # Compose area
            with Horizontal(id="compose-area"):
                yield Input(
                    placeholder="  Type a message and press Enter to send…",
                    id="compose-input",
                )
                yield Button("Send", variant="primary", id="send-btn")
                yield Button("Broadcast", id="broadcast-btn")

    def on_mount(self) -> None:
        self._title_tick = 0
        self._animate_title()
        self.set_interval(0.3, self._animate_title)
        self.refresh_inbox()
        self.set_interval(3.0, self.refresh_inbox)

    def _animate_title(self) -> None:
        self._title_tick += 1
        title = self.query_one("#mailbox-title", Label)
        text = Text()
        text.append(f" {spinner('braille', self._title_tick)} ", style=f"bold {theme.ACCENT_HI}")
        text.append("📬 MAIL", style=f"bold {theme.PINK}")
        stops = theme.GRADIENT_SESS
        for idx, ch in enumerate("BOX"):
            text.append(ch, style=f"bold {stops[idx % len(stops)]}")
        title.update(text)

    def watch_session_id(self, session_id: Optional[str]) -> None:
        """Re-load inbox when the active session changes."""
        self.refresh_inbox()

    def refresh_inbox(self) -> None:
        """Pull messages for the selected session and render them."""
        inbox_content = self.query_one("#inbox-content", Static)
        thread_content = self.query_one("#thread-content", Static)

        if self.session_id is None:
            inbox_content.update(
                Text("\n  Select a session to view\n  its mailbox.\n", style="dim italic")
            )
            thread_content.update(Text(""))
            return

        try:
            db = self.app.db  # type: ignore[attr-defined]

            # All messages involving this session
            rows = db.fetchall(
                """
                SELECT * FROM messages
                WHERE (to_session_id = ? OR from_session_id = ? OR to_session_id IS NULL)
                ORDER BY created_at DESC
                LIMIT 50
                """,
                (self.session_id, self.session_id),
            )
            messages = [dict(r) for r in rows]

            # Render inbox summary
            self._render_inbox(inbox_content, messages)

            # Render collision alerts prominently
            collisions = [m for m in messages if m.get("kind") == "collision"]
            if collisions:
                self._render_thread(thread_content, collisions, highlight_collisions=True)
            else:
                self._render_thread(thread_content, messages[:20])

        except Exception as exc:
            inbox_content.update(
                Text(f"\n  [bold #ff5d6b]error loading mailbox:[/]\n  {exc}", style=f"dim {theme.RED}")
            )

    def _render_inbox(self, widget: Static, messages: list[dict]) -> None:
        text = Text()

        if not messages:
            text.append("\n  No messages yet.\n", style="dim italic")
            widget.update(text)
            return

        # Group by kind
        by_kind: dict[str, int] = {}
        unclaimed = 0
        for m in messages:
            kind = m.get("kind") or "chat"
            by_kind[kind] = by_kind.get(kind, 0) + 1
            if m.get("claimed_at") is None and m.get("to_session_id") == self.session_id:
                unclaimed += 1

        text.append(f"\n  [bold #e6ddf0]{len(messages)} messages[/]")
        if unclaimed:
            text.append(f"  [bold #ff5d6b]({unclaimed} unclaimed)[/]")
        text.append("\n\n  [dim #5f566c]by type:[/]\n", style="dim")

        for kind, count in sorted(by_kind.items(), key=lambda x: -x[1]):
            glyph = KIND_GLYPHS.get(kind, "·")
            style = KIND_STYLES.get(kind, theme.TEXT)
            text.append(f"  {glyph} {kind:<12}", style=f"bold {style}")
            text.append(f" {count}\n", style=f"bold {style}")

        text.append("\n  [dim #5f566c]recent:[/]\n", style="dim")
        for m in messages[:8]:
            kind = m.get("kind") or "chat"
            glyph = KIND_GLYPHS.get(kind, "·")
            style = KIND_STYLES.get(kind, theme.TEXT)
            ts = _ts_str(m.get("created_at"))
            body = (m.get("body") or "")[:32]
            from_id = (m.get("from_session_id") or "broadcast")[:8]

            is_collision = kind == "collision"
            bg = f" on {theme.STATUS_BG['error']}" if is_collision else ""

            text.append(f"  {glyph} ", style=style)
            text.append(f"[{ts}] ", style=f"dim {theme.TEXT_FAINT}")
            text.append(f"{from_id}", style=f"dim {theme.CYAN}")
            text.append(f"\n    {body}…\n", style=style + bg)

        widget.update(text)

    def _render_thread(
        self,
        widget: Static,
        messages: list[dict],
        highlight_collisions: bool = False,
    ) -> None:
        text = Text()

        if not messages:
            text.append("\n  No thread selected.\n", style="dim italic")
            widget.update(text)
            return

        if highlight_collisions:
            text.append("  [bold #ff5d6b]⚠️  COLLISION ALERTS[/]\n")
            text.append("  " + "░" * 42 + "\n\n", style=f"dim {theme.TEXT_FAINT}")

        for m in reversed(messages[:20]):
            kind = m.get("kind") or "chat"
            glyph = KIND_GLYPHS.get(kind, "·")
            style = KIND_STYLES.get(kind, theme.TEXT)
            ts = _ts_str(m.get("created_at"))
            body = m.get("body") or "(empty)"
            from_id = (m.get("from_session_id") or "system")[:12]
            to_id = (m.get("to_session_id") or "broadcast")[:12]
            claimed = m.get("claimed_at") is not None
            intent = m.get("intent") or ""

            is_collision = kind == "collision"

            if is_collision:
                text.append("  ┌" + "─" * 50 + "┐\n", style=f"{theme.RED}")
                text.append(f"  │ {glyph} COLLISION  [{ts}]", style=f"bold {theme.RED}")
                text.append(" " * max(0, 29 - len(ts)) + "│\n", style=theme.RED)
                text.append(f"  │ {body[:48]:<48} │\n", style=theme.RED)
                text.append("  └" + "─" * 50 + "┘\n\n", style=theme.RED)
            else:
                # Direction arrow
                if m.get("to_session_id") == self.session_id:
                    arrow = "→ you"
                    arrow_style = theme.GREEN
                elif m.get("from_session_id") == self.session_id:
                    arrow = "← you"
                    arrow_style = theme.CYAN
                else:
                    arrow = "⊕ bcast"
                    arrow_style = theme.YELLOW

                claimed_mark = " ✓" if claimed else ""
                text.append(f"  {glyph} ", style=style)
                text.append(f"{from_id}", style=f"dim {theme.CYAN}")
                text.append(f" {arrow} ", style=arrow_style)
                text.append(f"{to_id}", style=f"dim {theme.CYAN}")
                text.append(f"  [{ts}]", style=f"dim {theme.TEXT_FAINT}")
                text.append(f"{claimed_mark}\n", style=f"dim {theme.GREEN}")

                kind_color = KIND_STYLES.get(kind, theme.TEXT)
                if intent:
                    text.append(f"  {kind.upper():^8}", style=f"bold {kind_color} on {theme.BG_PANEL_2}")
                    text.append(f"  intent: {intent}\n", style=f"dim {theme.TEXT_FAINT}")

                # Wrap body at 55 chars
                for line in _wrap(body, 55):
                    text.append(f"    {line}\n", style=style)
                text.append("\n")

        widget.update(text)

    # ─────────────────────────────────────────────────────────────────────────
    # Event handlers
    # ─────────────────────────────────────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id in ("send-btn", "broadcast-btn"):
            input_widget = self.query_one("#compose-input", Input)
            body = input_widget.value.strip()
            if not body or self.session_id is None:
                return

            try:
                db = self.app.db  # type: ignore[attr-defined]
                to_id = self.session_id if event.button.id == "send-btn" else None
                db.execute(
                    """
                    INSERT INTO messages (to_session_id, from_session_id, kind, body, intent, created_at)
                    VALUES (?, 'tui', 'chat', ?, 'inform', ?)
                    """,
                    (to_id, body, db.now_ms()),
                )
                input_widget.value = ""
                self.app.notify(  # type: ignore[attr-defined]
                    "Message sent",
                    severity="information",
                    timeout=2,
                )
                self.refresh_inbox()
            except Exception as exc:
                self.app.notify(str(exc), severity="error", timeout=4)  # type: ignore[attr-defined]

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "compose-input":
            self.query_one("#send-btn", Button).press()


# ─────────────────────────────────────────────────────────────────────────────
# Utility
# ─────────────────────────────────────────────────────────────────────────────

def _wrap(text: str, width: int) -> list[str]:
    """Simple word-wrap."""
    lines: list[str] = []
    while len(text) > width:
        cut = text.rfind(" ", 0, width)
        if cut == -1:
            cut = width
        lines.append(text[:cut])
        text = text[cut:].lstrip()
    lines.append(text)
    return lines
