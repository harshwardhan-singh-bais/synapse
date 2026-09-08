"""
Knowledge panel — browse, view, write and delete knowledge artifacts.

Left: artifact list (key + mime + size). Right: selected artifact content.
Action bar: write new / refresh / delete.
"""

from __future__ import annotations

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


class KnowledgePanel(Static):
    """Knowledge artifact browser + detail + actions."""

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("  🧠 KNOWLEDGE", id="knowledge-title", classes="dashboard-title")
            with Horizontal(id="knowledge-body"):
                with ScrollableContainer(id="knowledge-list"):
                    yield Label("  Artifacts", classes="panel-subtitle")
                    yield ListView(id="knowledge-list-view")
                with Vertical(id="knowledge-detail"):
                    yield Label("  Content", classes="panel-subtitle")
                    yield Static(id="knowledge-detail-content")
            with Horizontal(id="knowledge-actions"):
                yield Button("＋ Write", id="know-new-btn", variant="primary")
                yield Button("⧉ Copy", id="know-copy-btn", tooltip="Copy artifact content to clipboard")
                yield Button("✗ Delete", id="know-delete-btn", variant="error")

    def on_mount(self) -> None:
        self._artifacts: list[dict] = []
        self._selected_key: str | None = None
        self.refresh_artifacts()
        self.set_interval(3.0, self.refresh_artifacts)

    # ──────────────────────────────────────────────────────────────
    # Data
    # ──────────────────────────────────────────────────────────────

    def refresh_artifacts(self) -> None:
        if not self.visible:
            return
        try:
            db = self.app.db  # type: ignore[attr-defined]
            rows = db.fetchall(
                "SELECT * FROM knowledge_artifacts ORDER BY updated_at DESC LIMIT 200"
            )
            self._artifacts = [dict(r) for r in rows]

            view = self.query_one("#knowledge-list-view", ListView)
            view.clear()

            if not self._artifacts:
                view.append(
                    ListItem(Label("  [dim italic]no artifacts yet — press ＋ Write[/]"))
                )
                self._render_detail(None)
                return

            for a in self._artifacts:
                key = (a.get("key") or "?")[:30]
                mime = (a.get("mime_type") or "text/plain").split("/")[-1][:12]
                size = len(a.get("content") or "")
                text = Text()
                text.append(" 🧠 ", style=f"bold {theme.CYAN}")
                text.append(f"{key}", style=f"{theme.TEXT}")
                text.append(f"  {mime:<12}", style=f"dim {theme.TEXT_FAINT}")
                text.append(f" {size}B", style=f"dim {theme.TEXT_DIM}")
                item = ListItem(Label(text), id=f"know-{a['key']}")
                if a["key"] == self._selected_key:
                    item.add_class("selected-item")
                view.append(item)

            if self._selected_key is not None:
                self._render_detail(
                    next((a for a in self._artifacts if a["key"] == self._selected_key), None)
                )
            elif self._artifacts:
                self._selected_key = self._artifacts[0]["key"]
                self._render_detail(self._artifacts[0])
        except Exception:
            pass

    def _render_detail(self, artifact: dict | None) -> None:
        detail = self.query_one("#knowledge-detail-content", Static)
        if artifact is None:
            detail.update(Text("\n  Select an artifact to view its content.", style="dim italic"))
            return

        text = Text()
        text.append(f"  🧠 {artifact.get('key')}\n", style=f"bold {theme.TEXT}")
        text.append("  " + "─" * 46 + "\n", style=f"dim {theme.TEXT_FAINT}")
        text.append("  mime    ", style=f"bold {theme.TEXT_DIM}")
        text.append(f"{artifact.get('mime_type') or 'text/plain'}\n", style=f"dim {theme.TEXT_DIM}")
        text.append("  updated ", style=f"bold {theme.TEXT_DIM}")
        text.append(f"{_ts_str(artifact.get('updated_at'))}\n", style=f"dim {theme.TEXT_DIM}")
        text.append("\n")

        content = artifact.get("content") or ""
        for line in _wrap(content, 60)[:40]:
            text.append(f"  {line}\n", style=f"dim {theme.TEXT_DIM}")
        if len(_wrap(content, 60)) > 40:
            text.append("  … (truncated)\n", style="dim italic")

        detail.update(text)

    def _copy_selected(self) -> None:
        """Copy the selected artifact's content to the clipboard."""
        artifact = next(
            (a for a in self._artifacts if a["key"] == self._selected_key), None
        )
        if artifact is None:
            self.app.notify("No artifact selected.", severity="warning", timeout=2)  # type: ignore[attr-defined]
            return
        try:
            from ...clipboard import copy_to_clipboard

            if copy_to_clipboard(artifact.get("content") or ""):
                self.app.notify(  # type: ignore[attr-defined]
                    f"Copied '{artifact['key']}' to clipboard.",
                    severity="information",
                    timeout=2,
                )
            else:
                self.app.notify("Clipboard unavailable.", severity="warning", timeout=2)  # type: ignore[attr-defined]
        except Exception as exc:
            self.app.notify(f"Copy failed: {exc}", severity="error", timeout=4)  # type: ignore[attr-defined]

    # ──────────────────────────────────────────────────────────────
    # Selection & actions
    # ──────────────────────────────────────────────────────────────

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item_id: str = event.item.id or ""
        if item_id.startswith("know-"):
            self._selected_key = item_id[5:]
            artifact = next(
                (a for a in self._artifacts if a["key"] == self._selected_key), None
            )
            self._render_detail(artifact)
            for child in self.query_one("#knowledge-list-view", ListView).children:
                child.remove_class("selected-item")
            event.item.add_class("selected-item")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "know-new-btn":
            self.app.action_new_artifact()  # type: ignore[attr-defined]
        elif btn_id == "know-copy-btn":
            self._copy_selected()
        elif btn_id == "know-delete-btn":
            if self._selected_key is None:
                self.app.notify("No artifact selected.", severity="warning", timeout=2)  # type: ignore[attr-defined]
                return
            try:
                db = self.app.db  # type: ignore[attr-defined]
                db.execute("DELETE FROM knowledge_artifacts WHERE key=?", (self._selected_key,))
                self.app.notify(  # type: ignore[attr-defined]
                    f"Artifact '{self._selected_key}' deleted.",
                    severity="warning",
                    timeout=2,
                )
                self._selected_key = None
                self.refresh_artifacts()
            except Exception as exc:
                self.app.notify(str(exc), severity="error", timeout=4)  # type: ignore[attr-defined]


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