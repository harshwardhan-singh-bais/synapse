"""
Automations panel — scheduled jobs & their run history.

Left: automation list (name + schedule + enabled state).
Right: selected automation detail.
Bottom: recent run history. Action bar: create / trigger / toggle / delete.
"""

from __future__ import annotations

import threading
import time

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.widgets import Button, Label, ListItem, ListView, Static

from .. import theme


def _ts_str(ms: int | None) -> str:
    if not ms:
        return "—"
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ms // 1000))


class AutomationPanel(Static):
    """Automation list + detail + history + actions."""

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("  ⏱ AUTOMATIONS", id="automations-title", classes="dashboard-title")
            # (title kept static — no spinner)
            with Horizontal(id="automations-body"):
                with ScrollableContainer(id="automations-list"):
                    yield Label("  Schedules", classes="panel-subtitle")
                    yield ListView(id="automation-list")
                with Vertical(id="automation-detail"):
                    yield Label("  Detail", classes="panel-subtitle")
                    yield Static(id="automation-detail-content")
            with Vertical(id="automation-history"):
                yield Label("  Run History", classes="panel-subtitle")
                yield Static(id="automation-history-content")
            with Horizontal(id="automations-actions"):
                yield Button("＋ New", id="auto-new-btn", variant="primary")
                yield Button("▶ Trigger", id="auto-trigger-btn")
                yield Button("⏻ Toggle", id="auto-toggle-btn")
                yield Button("✗ Delete", id="auto-delete-btn", variant="error")

    def on_mount(self) -> None:
        self._automations: list[dict] = []
        self._selected_id: str | None = None
        self.refresh_automations()
        self.set_interval(3.0, self.refresh_automations)

    # ──────────────────────────────────────────────────────────────
    # Data
    # ──────────────────────────────────────────────────────────────

    def refresh_automations(self) -> None:
        if not self.visible:
            return
        try:
            db = self.app.db  # type: ignore[attr-defined]
            rows = db.fetchall(
                "SELECT * FROM automations ORDER BY created_at DESC LIMIT 100"
            )
            self._automations = [dict(r) for r in rows]

            auto_list = self.query_one("#automation-list", ListView)
            auto_list.clear()

            if not self._automations:
                auto_list.append(
                    ListItem(Label("  [dim italic]no automations yet — press ＋ New[/]"))
                )
                self._render_detail(None)
            else:
                for a in self._automations:
                    enabled = a.get("enabled")
                    name = (a.get("name") or "(unnamed)")[:30]
                    text = Text()
                    text.append(" ⏱ " if enabled else " ○ ", style=f"bold {theme.GREEN if enabled else theme.TEXT_FAINT}")
                    text.append(f"{name}", style=f"{theme.TEXT}")
                    text.append(f"  {a.get('schedule_kind')}({a.get('schedule_spec')})", style=f"dim {theme.TEXT_FAINT}")
                    item = ListItem(Label(text), id=f"auto-{a['id']}")
                    if a["id"] == self._selected_id:
                        item.add_class("selected-item")
                    auto_list.append(item)

            self._render_history()
            if self._selected_id is not None:
                self._render_detail(
                    next((a for a in self._automations if a["id"] == self._selected_id), None)
                )
            elif self._automations:
                self._selected_id = self._automations[0]["id"]
                self._render_detail(self._automations[0])
        except Exception:
            pass

    def _render_detail(self, auto: dict | None) -> None:
        detail = self.query_one("#automation-detail-content", Static)
        if auto is None:
            detail.update(Text("\n  Select an automation to inspect it.", style="dim italic"))
            return

        enabled = auto.get("enabled")
        text = Text()
        text.append(" ⏱ " if enabled else " ○ ", style=f"bold {theme.GREEN if enabled else theme.TEXT_FAINT}")
        text.append(f"{auto.get('name') or '(unnamed)'}\n", style=f"bold {theme.TEXT}")
        text.append("  " + "─" * 44 + "\n\n", style=f"dim {theme.TEXT_FAINT}")

        text.append("  state     ", style=f"bold {theme.TEXT_DIM}")
        text.append(f"{'enabled' if enabled else 'disabled'}\n", style=f"bold {theme.GREEN if enabled else theme.TEXT_FAINT}")
        text.append("  schedule  ", style=f"bold {theme.TEXT_DIM}")
        text.append(f"{auto.get('schedule_kind')}({auto.get('schedule_spec')})\n", style=f"bold {theme.CYAN}")
        text.append("  tz        ", style=f"bold {theme.TEXT_DIM}")
        text.append(f"{auto.get('timezone') or 'UTC'}\n", style=f"dim {theme.TEXT_DIM}")
        text.append("  next run  ", style=f"bold {theme.TEXT_DIM}")
        text.append(f"{_ts_str(auto.get('next_run_at'))}\n", style=f"dim {theme.TEXT_DIM}")
        text.append("  action    ", style=f"bold {theme.TEXT_DIM}")
        text.append(f"{auto.get('action_kind') or '?'}\n", style=f"bold {theme.PURPLE}")

        if auto.get("prompt"):
            text.append("\n  prompt\n", style=f"bold {theme.TEXT_DIM}")
            for line in _wrap(auto["prompt"], 44):
                text.append(f"  {line}\n", style=f"dim {theme.TEXT_DIM}")

        if auto.get("action_command"):
            text.append("\n  command\n", style=f"bold {theme.TEXT_DIM}")
            for line in _wrap(auto["action_command"], 44):
                text.append(f"  {line}\n", style=f"dim {theme.TEXT_DIM}")

        if auto.get("action_target_session"):
            text.append("\n  target    ", style=f"bold {theme.TEXT_DIM}")
            text.append(f"{auto['action_target_session'][:40]}\n", style=f"dim {theme.TEXT_DIM}")
        if auto.get("action_repo_path"):
            text.append("  repo      ", style=f"bold {theme.TEXT_DIM}")
            text.append(f"{auto['action_repo_path'][:40]}\n", style=f"dim {theme.TEXT_DIM}")

        detail.update(text)

    def _render_history(self) -> None:
        content = self.query_one("#automation-history-content", Static)
        try:
            db = self.app.db  # type: ignore[attr-defined]
            rows = db.fetchall(
                "SELECT * FROM automation_runs ORDER BY fired_at DESC LIMIT 10"
            )
            text = Text()
            if not rows:
                text.append("  No runs recorded.\n", style="dim italic")
                content.update(text)
                return
            for r in rows:
                success = r.get("success")
                color = theme.GREEN if success else theme.RED
                glyph = "✓" if success else "✗"
                name = (r.get("automation_name") or r.get("automation_id", "?"))[:20]
                text.append(f"  {glyph} ", style=f"bold {color}")
                text.append(f"[{_ts_str(r.get('fired_at'))}]", style=f"dim {theme.TEXT_FAINT}")
                text.append(f" {name:<20}", style=f"bold {theme.CYAN}")
                text.append(f" {r.get('action_kind') or '?':<8}", style=f"dim {theme.TEXT_DIM}")
                text.append(f" {(r.get('result') or '')[:28]}\n", style=f"dim {theme.TEXT_DIM}")
            content.update(text)
        except Exception:
            pass

    # ──────────────────────────────────────────────────────────────
    # Selection
    # ──────────────────────────────────────────────────────────────

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item_id: str = event.item.id or ""
        if item_id.startswith("auto-"):
            self._selected_id = item_id[5:]
            auto = next((a for a in self._automations if a["id"] == self._selected_id), None)
            self._render_detail(auto)
            for child in self.query_one("#automation-list", ListView).children:
                child.remove_class("selected-item")
            event.item.add_class("selected-item")

    # ──────────────────────────────────────────────────────────────
    # Actions
    # ──────────────────────────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "auto-new-btn":
            self.app.action_new_automation()  # type: ignore[attr-defined]
            return
        if self._selected_id is None:
            self.app.notify("No automation selected.", severity="warning", timeout=2)  # type: ignore[attr-defined]
            return
        if btn_id == "auto-trigger-btn":
            self._trigger_selected()
        elif btn_id == "auto-toggle-btn":
            self._toggle_selected()
        elif btn_id == "auto-delete-btn":
            self._delete_selected()

    def _toggle_selected(self) -> None:
        try:
            db = self.app.db  # type: ignore[attr-defined]
            auto = next((a for a in self._automations if a["id"] == self._selected_id), None)
            if auto is None:
                return
            new_state = 0 if auto.get("enabled") else 1
            db.execute(
                "UPDATE automations SET enabled=?, updated_at=? WHERE id=?",
                (new_state, db.now_ms(), self._selected_id),
            )
            self.app.notify(  # type: ignore[attr-defined]
                f"Automation {'enabled' if new_state else 'disabled'}.",
                severity="information",
                timeout=2,
            )
            self.refresh_automations()
        except Exception as exc:
            self.app.notify(str(exc), severity="error", timeout=4)  # type: ignore[attr-defined]

    def _delete_selected(self) -> None:
        try:
            db = self.app.db  # type: ignore[attr-defined]
            db.execute(
                "UPDATE automations SET enabled=0, name=('[deleted] ' || name) WHERE id=?",
                (self._selected_id,),
            )
            self.app.notify("Automation deleted.", severity="warning", timeout=2)  # type: ignore[attr-defined]
            self._selected_id = None
            self.refresh_automations()
        except Exception as exc:
            self.app.notify(str(exc), severity="error", timeout=4)  # type: ignore[attr-defined]

    def _trigger_selected(self) -> None:
        auto = next((a for a in self._automations if a["id"] == self._selected_id), None)
        if auto is None:
            return
        self.app.notify(  # type: ignore[attr-defined]
            f"Triggering {auto.get('name') or auto['id'][:8]}…",
            severity="information",
            timeout=3,
        )
        threading.Thread(
            target=self._trigger_worker,
            args=(auto,),
            daemon=True,
            name=f"auto-trigger-{auto['id'][:8]}",
        ).start()

    def _trigger_worker(self, auto: dict) -> None:
        app = self.app  # type: ignore[attr-defined]
        try:
            from ...automation.scheduler import AutomationScheduler
            from ...backend.tmux import TmuxBackend
            from ...session.manager import SessionManager

            db = app.db
            mgr = SessionManager(db, TmuxBackend(), app.config)
            scheduler = AutomationScheduler(db, mgr)
            scheduler._fire(auto, db.now_ms())
            app.call_from_thread(
                app.notify, "Automation fired.", severity="information", timeout=3
            )
        except Exception as exc:
            app.call_from_thread(app.notify, f"Trigger failed: {exc}", severity="error", timeout=5)
        finally:
            app.call_from_thread(self.refresh_automations)


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