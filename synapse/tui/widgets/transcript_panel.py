"""
Transcripts panel — browse, read and search agent conversation transcripts.

Uses the transcript reader backends (Claude / Gemini / Codex / Cursor /
Kimi / OpenCode) to list available transcript files and render their
exchanges. Full-text search runs across every supported tool.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.widgets import Button, Input, Label, ListItem, ListView, Static

from .. import theme

TOOL_GLYPHS: dict[str, str] = {
    "claude":   "◆",
    "gemini":   "◇",
    "codex":    "◆",
    "cursor":   "◇",
    "kimi":     "◆",
    "opencode": "◇",
}


def _discover_transcript_files() -> list[dict]:
    """Find transcript files for every supported tool."""
    files: list[dict] = []
    home = Path.home()
    roots = [
        ("claude",   home / ".claude" / "projects"),
        ("gemini",   home / ".gemini" / "sessions"),
        ("codex",    home / ".codex" / "sessions"),
        ("cursor",   home / ".cursor" / "sessions"),
        ("kimi",     home / ".kimi" / "sessions"),
        ("opencode", home / ".opencode"),
    ]
    for tool, root in roots:
        if not root.exists():
            continue
        try:
            for p in sorted(root.rglob("*.jsonl"), key=lambda x: x.stat().st_mtime, reverse=True):
                files.append({"tool": tool, "path": p, "size": p.stat().st_size})
        except OSError:
            continue
    return files[:200]


class TranscriptPanel(Static):
    """Transcript list + detail + search."""

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("  ⇬ Transcripts", id="transcripts-title", classes="dashboard-title")
            with Horizontal(id="transcripts-body"):
                with ScrollableContainer(id="transcripts-list"):
                    yield Label("  Files", classes="panel-subtitle")
                    yield ListView(id="transcript-list")
                with Vertical(id="transcript-detail"):
                    yield Label("  Content", classes="panel-subtitle")
                    with ScrollableContainer():
                        yield Static(id="transcript-detail-content")
            with Horizontal(id="transcript-search-row"):
                yield Input(placeholder="  Search all transcripts…", id="transcript-search-input")
                yield Button("Search", id="transcript-search-btn")

    def on_mount(self) -> None:
        self._files: list[dict] = []
        self._selected: Optional[Path] = None
        self.refresh_files()

    # ──────────────────────────────────────────────────────────────────
    # Data
    # ──────────────────────────────────────────────────────────────────

    def refresh_files(self) -> None:
        self._files = _discover_transcript_files()
        view = self.query_one("#transcript-list", ListView)
        view.clear()

        if not self._files:
            view.append(
                ListItem(Label(
                    "  [dim italic]no transcripts found on this machine[/]\n"
                    "  [dim italic](~/.claude, ~/.gemini, ~/.codex …)[/]"
                ))
            )
            return

        for f in self._files:
            tool = f["tool"]
            glyph = TOOL_GLYPHS.get(tool, "·")
            path: Path = f["path"]
            size_kb = max(1, f["size"] // 1024)
            text = Text()
            text.append(f" {glyph} ", style=f"bold {theme.ACCENT_HI}")
            text.append(f"{tool:<9}", style=f"bold {theme.CYAN}")
            text.append(f"{path.name[:28]:<28}", style=theme.TEXT)
            text.append(f" {size_kb:>5} KB", style=f"dim {theme.TEXT_FAINT}")
            view.append(ListItem(Label(text), id=f"tx-{abs(hash(str(path))) % 10_000_000}"))

    def _render_detail(self, path: Optional[Path]) -> None:
        detail = self.query_one("#transcript-detail-content", Static)
        if path is None:
            detail.update(Text("\n  Select a transcript to read it.", style="dim italic"))
            return
        try:
            from ...transcript.reader import read_transcript

            t = read_transcript(path)
            text = Text()
            text.append(f"  {path}\n", style=f"dim {theme.TEXT_FAINT}")
            text.append(
                f"  {t.tool} · {len(t.exchanges)} exchanges\n",
                style=f"bold {theme.ACCENT_HI}",
            )
            text.append("  " + "─" * 50 + "\n\n", style=f"dim {theme.EDGE}")

            for ex in t.exchanges[-60:]:
                role = (ex.role or "?").lower()
                if role == "user":
                    tag, color = "you       ", theme.GREEN
                elif role == "assistant":
                    tag, color = "assistant ", theme.ACCENT_HI
                else:
                    tag, color = "tool      ", theme.CYAN
                body = (ex.content or "").strip().replace("\n", " ")
                if ex.tool_name:
                    body = f"[{ex.tool_name}] {body}" if body else f"[{ex.tool_name}]"
                if not body:
                    continue
                text.append(f"  {tag}", style=f"bold {color}")
                for line in _wrap(body[:400], 58)[:8]:
                    text.append(f"{line}\n", style=f"dim {theme.TEXT_DIM}")
                text.append("\n")
            detail.update(text)
        except Exception as exc:
            detail.update(Text(f"\n  Failed to read transcript:\n  {exc}", style=f"dim {theme.RED}"))

    # ──────────────────────────────────────────────────────────────────
    # Events
    # ──────────────────────────────────────────────────────────────────

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        idx = event.item.id
        if idx and idx.startswith("tx-"):
            n = int(idx[3:])
            if 0 <= n < len(self._files):
                self._selected = self._files[n]["path"]
                self._render_detail(self._selected)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "transcript-search-btn":
            self._run_search()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "transcript-search-input":
            self._run_search()

    def _run_search(self) -> None:
        query = self.query_one("#transcript-search-input", Input).value.strip()
        if not query:
            return
        self.app.notify("Searching transcripts…", severity="information", timeout=2)  # type: ignore[attr-defined]
        threading.Thread(
            target=self._search_worker, args=(query,), daemon=True, name="tx-search"
        ).start()

    def _search_worker(self, query: str) -> None:
        try:
            from ...transcript.reader import search_transcripts

            results = search_transcripts(query, max_results=30)
            self.app.call_from_thread(self._render_search_results, query, results)  # type: ignore[attr-defined]
        except Exception as exc:
            self.app.call_from_thread(  # type: ignore[attr-defined]
                self.app.notify, f"Search failed: {exc}", severity="error", timeout=4
            )

    def _render_search_results(self, query: str, results: list[dict]) -> None:
        detail = self.query_one("#transcript-detail-content", Static)
        text = Text()
        text.append(f'  Search: "{query}" — {len(results)} hit(s)\n', style=f"bold {theme.ACCENT_HI}")
        text.append("  " + "─" * 50 + "\n\n", style=f"dim {theme.EDGE}")
        if not results:
            text.append("  No matches found.\n", style="dim italic")
        for r in results:
            text.append(f"  [{r['tool']}] ", style=f"bold {theme.CYAN}")
            text.append(f"{Path(r['path']).name}\n", style=theme.TEXT)
            text.append(f"    {r['role']}: ", style=f"dim {theme.TEXT_FAINT}")
            text.append(f"{r['content_preview'][:120]}\n\n", style=f"dim {theme.TEXT_DIM}")
        detail.update(text)


def _wrap(text: str, width: int) -> list[str]:
    lines: list[str] = []
    while len(text) > width:
        cut = text.rfind(" ", 0, width)
        if cut == -1:
            cut = width
        lines.append(text[:cut])
        text = text[cut:].lstrip()
    lines.append(text)
    return lines
