"""
Orchestration dashboard — live view of runs, stages, cycles, and cost.
The centrepiece of Synapse: shows autonomous work happening in real time.
"""
from __future__ import annotations

import json
import time
from typing import Optional

from textual.app import ComposeResult
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.reactive import reactive
from textual.widgets import DataTable, Label, Log, ProgressBar, Static
from rich.text import Text

from .. import theme
from ..ascii import rainbow_bar, spinner


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _fmt_cost(v: Optional[float]) -> str:
    if v is None:
        return "$0.00"
    return f"${v:.4f}"


def _elapsed(started_ms: Optional[int]) -> str:
    if started_ms is None:
        return "—"
    secs = int(time.time()) - started_ms // 1000
    m, s = divmod(secs, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


STATUS_GLYPHS: dict[str, str] = {
    "running":   "⟳",
    "completed": "✓",
    "failed":    "✗",
    "paused":    "⏸",
    "pending":   "○",
}

STATUS_STYLES: dict[str, str] = {
    "running":   theme.GREEN,
    "completed": theme.CYAN,
    "failed":    theme.RED,
    "paused":    theme.YELLOW,
    "pending":   theme.TEXT_FAINT,
}


# ─────────────────────────────────────────────────────────────────────────────
# Sub-widgets
# ─────────────────────────────────────────────────────────────────────────────

class RunCard(Static):
    """A single run's status card with stage progress and cost summary."""

    DEFAULT_CSS = """
    RunCard {
        height: auto;
        margin: 0 0 1 0;
        padding: 1;
        border: solid $surface-lighten-2;
    }
    """

    def __init__(self, run: dict, stages: list[dict], cycles: list[dict], **kwargs):
        super().__init__(**kwargs)
        self._run = run
        self._stages = stages
        self._cycles = cycles

    def render(self) -> Text:  # type: ignore[override]
        run = self._run
        stages = self._stages
        cycles = self._cycles

        status = (run.get("status") or "unknown").lower()
        glyph = STATUS_GLYPHS.get(status, "?")
        style = STATUS_STYLES.get(status, theme.TEXT_DIM)
        mode = (run.get("mode") or "goal").upper()
        goal = (run.get("goal") or "No goal specified")
        run_id_short = (run.get("id") or "?")[:8]
        elapsed = _elapsed(run.get("started_at"))

        # Cost aggregation
        total_api = sum((c.get("api_cost_usd") or 0.0) for c in cycles)
        total_virt = sum((c.get("virtual_cost_usd") or 0.0) for c in cycles)
        total_exch = sum((c.get("exchanges") or 0) for c in cycles)

        text = Text()
        # ── Corner decoration + status ───────────────────────────────────────
        text.append("┌", style=f"bold {style}")
        text.append(f" {glyph} [{mode}] {run_id_short} ", style=f"bold {style}")
        text.append("┐", style=f"bold {style}")
        text.append(f"  ⏱ {elapsed}", style=f"dim {theme.TEXT_FAINT}")
        text.append("\n")
        text.append(f"│ {goal[:62]}", style="italic #efe9e0")
        text.append("\n")

        # ── Stage progress (rainbow bar) ────────────────────────────────────
        total_stages = len(stages)
        done_stages = sum(
            1 for s in stages if (s.get("status") or "") in ("completed", "failed")
        )
        running_stage = next(
            (s for s in stages if (s.get("status") or "") == "running"), None
        )

        if total_stages:
            pct = int(done_stages / total_stages * 100)
            bar = rainbow_bar(pct, 16)
            text.append(f"│ {done_stages:>2}/{total_stages:<2}", style=f"bold {theme.CYAN}")
            text.append(f" {bar} \n", style="bold")

            if running_stage:
                stage_name = running_stage.get("name") or f"Stage {running_stage.get('stage_index', '?')}"
                text.append(f"│ ▶ {stage_name}", style=f"bold {theme.GREEN}")
                text.append("  (click to follow)", style=f"dim {theme.TEXT_FAINT}")
            text.append("\n")

        # ── Cost + exchanges ─────────────────────────────────────────────────
        text.append("└", style=f"bold {style}")
        text.append(" API ", style=f"dim {theme.TEXT_FAINT}")
        text.append(_fmt_cost(total_api), style=f"bold {theme.ORANGE}")
        text.append(f"  VIRT {_fmt_cost(total_virt)}", style=f"bold {theme.PURPLE}")
        text.append(f"  ⇄ {total_exch}", style=f"bold {theme.CYAN}")
        text.append(" ┘", style=f"bold {style}")

        return text


class VerificationFeed(Static):
    """Scrolling feed of cycle verdicts."""

    DEFAULT_CSS = """
    VerificationFeed {
        height: 12;
        border: solid $surface-lighten-2;
        padding: 0 1;
        overflow-y: auto;
    }
    """

    def __init__(self, cycles: list[dict], **kwargs):
        super().__init__(**kwargs)
        self._cycles = cycles

    def render(self) -> Text:  # type: ignore[override]
        text = Text()
        text.append("  VERIFICATION FEED\n", style="bold #7ee787")
        text.append("  " + "─" * 50 + "\n", style="dim")

        if not self._cycles:
            text.append("  No cycles recorded yet.\n", style="dim italic")
            return text

        for c in self._cycles[-20:]:  # last 20 cycles
            cycle_idx = c.get("cycle_index", "?")
            success = c.get("success", 0)
            finished = c.get("finished", 0)
            summary = (c.get("summary") or "")[:60]

            if not finished:
                text.append(f"  ⟳  Cycle {cycle_idx}: ", style="bright_green")
                text.append("running…\n", style="dim")
            elif success:
                text.append(f"  ✅ Cycle {cycle_idx}: ", style="bright_green bold")
                text.append("ACCEPTED", style="bright_green bold")
                if summary:
                    text.append(f" — {summary}", style="dim")
                text.append("\n")
            else:
                text.append(f"  ❌ Cycle {cycle_idx}: ", style="bright_red bold")
                text.append("REJECTED", style="bright_red bold")
                if summary:
                    text.append(f" — {summary}", style="dim #f85149")
                text.append("\n")

        return text


# ─────────────────────────────────────────────────────────────────────────────
# Main dashboard widget
# ─────────────────────────────────────────────────────────────────────────────

class OrchestrationDashboard(Static):
    """
    Live dashboard showing:
    - Active runs with stage progress bars
    - Scrolling verification feed (✅ ACCEPTED / ❌ REJECTED)
    - Cost ledger: API vs Virtual spend
    - Stage breakdown table
    """

    DEFAULT_CSS = """
    OrchestrationDashboard {
        height: 1fr;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("⚡ RUNS DASHBOARD", id="dash-title", classes="dashboard-title")
            with Horizontal(id="dash-top"):
                with ScrollableContainer(id="runs-panel"):
                    yield Label("  Active Runs", classes="panel-subtitle")
                    yield Static(id="runs-content")
                with ScrollableContainer(id="feed-panel"):
                    yield Label("  Verification Feed", classes="panel-subtitle")
                    yield Static(id="feed-content")
            with ScrollableContainer(id="stages-panel"):
                yield Label("  Stage Breakdown", classes="panel-subtitle")
                table = DataTable(id="stages-table", zebra_stripes=True)
                table.cursor_type = "row"
                yield table
            with ScrollableContainer(id="cost-panel"):
                yield Label("  Cost Ledger", classes="panel-subtitle")
                cost_table = DataTable(id="cost-table", zebra_stripes=True)
                cost_table.cursor_type = "row"
                yield cost_table

    def on_mount(self) -> None:
        # Set up stages table columns
        stages_table = self.query_one("#stages-table", DataTable)
        stages_table.add_columns(
            "Run", "Stage", "Name", "Status", "Cycles", "Elapsed"
        )

        # Set up cost table columns
        cost_table = self.query_one("#cost-table", DataTable)
        cost_table.add_columns(
            "Run", "Bucket", "Model", "Amount", "Tokens In", "Tokens Out"
        )

        self._title_tick = 0
        self._animate_title()
        self.set_interval(0.3, self._animate_title)
        self.refresh_data()
        self.set_interval(3.0, self.refresh_data)

    def refresh_data(self) -> None:
        """Pull all run/stage/cycle data from DB and re-render."""
        try:
            db = self.app.db  # type: ignore[attr-defined]

            runs = [
                dict(r) for r in db.fetchall(
                    "SELECT * FROM runs ORDER BY created_at DESC LIMIT 20"
                )
            ]
            stages = [dict(r) for r in db.fetchall("SELECT * FROM stages ORDER BY run_id, stage_index")]
            cycles = [dict(r) for r in db.fetchall("SELECT * FROM cycles ORDER BY run_id, cycle_index")]
            cost_rows = [
                dict(r) for r in db.fetchall(
                    "SELECT * FROM cost_ledger ORDER BY created_at DESC LIMIT 50"
                )
            ]

            self._render_runs(runs, stages, cycles)
            self._render_feed(runs, cycles)
            self._render_stages_table(runs, stages, cycles)
            self._render_cost_table(runs, cost_rows)

        except Exception:
            pass

    def _animate_title(self) -> None:
        self._title_tick += 1
        title = self.query_one("#dash-title", Label)
        text = Text()
        text.append(f" {spinner('braille', self._title_tick)} ", style=f"bold {theme.ACCENT_HI}")
        text.append("⚡ RUNS ", style=f"bold {theme.YELLOW}")
        stops = theme.GRADIENT_RUN
        for idx, ch in enumerate("DASHBOARD"):
            text.append(ch, style=f"bold {stops[idx % len(stops)]}")
        title.update(text)

    def _render_runs(
        self, runs: list[dict], stages: list[dict], cycles: list[dict]
    ) -> None:
        runs_content = self.query_one("#runs-content", Static)

        if not runs:
            runs_content.update(
                Text(
                    "\n  [dim]no orchestration runs yet…[/]\n\n"
                    "  [dim]use [/][bold #ffd166]synapse orchestrate goal[/][dim] to start a run.[/]\n",
                )
            )
            return

        text = Text()
        for run in runs[:5]:
            run_id = run.get("id") or ""
            run_stages = [s for s in stages if s.get("run_id") == run_id]
            run_cycles = [c for c in cycles if c.get("run_id") == run_id]

            status = (run.get("status") or "unknown").lower()
            glyph = STATUS_GLYPHS.get(status, "?")
            style = STATUS_STYLES.get(status, theme.TEXT_DIM)
            mode = (run.get("mode") or "goal").upper()
            goal = (run.get("goal") or "No goal")[:54]
            elapsed = _elapsed(run.get("started_at"))
            run_id_short = run_id[:8]

            text.append(f"\n  {glyph} ", style=f"bold {style}")
            text.append(f"[{mode}] ", style=f"bold {style}")
            text.append(f"{run_id_short}", style=f"dim {theme.TEXT_FAINT}")
            text.append(f"  ⏱ {elapsed}\n", style=f"dim {theme.TEXT_FAINT}")
            text.append(f"    {goal}\n", style="italic #efe9e0")

            total_stages = len(run_stages)
            done_stages = sum(
                1 for s in run_stages if (s.get("status") or "") in ("completed", "failed")
            )
            if total_stages:
                pct = int(done_stages / total_stages * 100)
                bar = rainbow_bar(pct, 22)
                text.append(f"    {bar}\n", style="bold")

            running_stage = next(
                (s for s in run_stages if (s.get("status") or "") == "running"), None
            )
            if running_stage:
                stage_name = running_stage.get("name") or f"Stage {running_stage.get('stage_index', '?')}"
                cycle_count = len([c for c in run_cycles if c.get("stage_id") == running_stage.get("id")])
                text.append(f"    ▶ {stage_name}", style=f"bold {theme.GREEN}")
                text.append(f"  cycle #{cycle_count}\n", style=f"dim {theme.GREEN}")

            total_api = sum((c.get("api_cost_usd") or 0.0) for c in run_cycles)
            total_virt = sum((c.get("virtual_cost_usd") or 0.0) for c in run_cycles)
            total_exch = sum((c.get("exchanges") or 0) for c in run_cycles)
            text.append(f"    API ", style=f"dim {theme.TEXT_FAINT}")
            text.append(_fmt_cost(total_api), style=f"bold {theme.ORANGE}")
            text.append(f"  VIRT ", style=f"dim {theme.TEXT_FAINT}")
            text.append(_fmt_cost(total_virt), style=f"bold {theme.PURPLE}")
            text.append(f"  ⇄ {total_exch}\n", style=f"bold {theme.CYAN}")
            text.append("    " + "░" * 55 + "\n", style=f"dim {theme.TEXT_FAINT}")

        runs_content.update(text)

    def _render_feed(self, runs: list[dict], cycles: list[dict]) -> None:
        feed_content = self.query_one("#feed-content", Static)

        text = Text()
        text.append(f" {spinner('braille', self._title_tick)} ", style=f"bold {theme.ACCENT_HI}")
        text.append("LIVE VERIFICATION FEED\n", style=f"bold {theme.GREEN}")
        text.append("  " + "░" * 46 + "\n", style=f"dim {theme.TEXT_FAINT}")

        if not cycles:
            text.append("  No cycles recorded.\n", style="dim italic")
            feed_content.update(text)
            return

        # Show the last 20 cycles across all runs, sorted by id desc
        recent = sorted(cycles, key=lambda c: c.get("id", 0), reverse=True)[:20]
        recent.reverse()

        for c in recent:
            run_id_short = (c.get("run_id") or "?")[:6]
            cycle_idx = c.get("cycle_index", "?")
            success = c.get("success", 0)
            finished = c.get("finished", 0)
            summary = (c.get("summary") or "")[:45]

            if not finished:
                text.append(f"  ⟳  [{run_id_short}] Cycle {cycle_idx}", style=f"bold {theme.GREEN}")
                text.append(": running…\n", style=f"dim {theme.TEXT_FAINT}")
            elif success:
                text.append(f"  ✅ [{run_id_short}] Cycle {cycle_idx}: ACCEPTED", style=f"bold {theme.GREEN}")
                if summary:
                    text.append(f"\n        {summary}", style=f"dim {theme.TEXT_DIM}")
                text.append("\n")
            else:
                text.append(f"  ❌ [{run_id_short}] Cycle {cycle_idx}: REJECTED", style=f"bold {theme.RED}")
                if summary:
                    text.append(f"\n        {summary}", style=f"dim {theme.RED}")
                text.append("\n")

        feed_content.update(text)

    def _render_stages_table(
        self, runs: list[dict], stages: list[dict], cycles: list[dict]
    ) -> None:
        table = self.query_one("#stages-table", DataTable)
        table.clear()

        run_lookup = {r.get("id"): r for r in runs}

        for stage in stages[:50]:
            run_id = stage.get("run_id") or "?"
            run = run_lookup.get(run_id, {})
            mode = (run.get("mode") or "?").upper()
            run_short = run_id[:6]

            stage_idx = stage.get("stage_index", "?")
            name = (stage.get("name") or "Unnamed")[:28]
            status = stage.get("status") or "pending"
            glyph = STATUS_GLYPHS.get(status, "?")
            style = STATUS_STYLES.get(status, "white")

            stage_id = stage.get("id")
            stage_cycles = [c for c in cycles if c.get("stage_id") == stage_id]
            num_cycles = len(stage_cycles)

            started = stage.get("started_at")
            completed = stage.get("completed_at")
            if started and completed:
                secs = (completed - started) // 1000
                m, s = divmod(secs, 60)
                elapsed = f"{m}m {s}s" if m else f"{s}s"
            elif started:
                elapsed = _elapsed(started)
            else:
                elapsed = "—"

            status_text = Text(f"{glyph} {status}", style=style)

            table.add_row(
                f"{mode}/{run_short}",
                str(stage_idx),
                name,
                status_text,
                str(num_cycles),
                elapsed,
            )

    def _render_cost_table(self, runs: list[dict], cost_rows: list[dict]) -> None:
        table = self.query_one("#cost-table", DataTable)
        table.clear()

        run_lookup = {r.get("id"): r for r in runs}

        for row in cost_rows:
            run_id = row.get("run_id") or "?"
            run = run_lookup.get(run_id, {})
            run_short = run_id[:6]
            mode = (run.get("mode") or "?").upper()

            bucket = row.get("bucket") or "api"
            model = (row.get("model") or "?")[:20]
            amount = row.get("amount_usd") or 0.0
            tokens_in = row.get("tokens_in") or 0
            tokens_out = row.get("tokens_out") or 0

            bucket_style = theme.ORANGE if bucket == "api" else theme.PURPLE
            amount_text = Text(f"${amount:.4f}", style=f"bold {bucket_style}")

            table.add_row(
                f"{mode}/{run_short}",
                bucket,
                model,
                amount_text,
                f"{tokens_in:,}",
                f"{tokens_out:,}",
            )
