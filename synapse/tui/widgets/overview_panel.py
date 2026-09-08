"""
Overview panel — the Synapse control centre.

A single glanceable screen summarising every subsystem: sessions, runs,
tasks, automations, mailbox, knowledge and relay, plus recent activity.
"""

from __future__ import annotations

import time

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import ScrollableContainer, Vertical
from textual.widgets import Label, Static

from .. import theme


def _ts_str(ms: int | None) -> str:
    if not ms:
        return "—"
    return time.strftime("%H:%M:%S", time.localtime(ms // 1000))


class OverviewPanel(Static):
    """Live status overview of the whole Synapse mesh."""

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("  ⌂ Overview", id="overview-title", classes="dashboard-title")
            with ScrollableContainer(id="overview-scroll"):
                yield Static(id="overview-content")

    def on_mount(self) -> None:
        self.refresh_data()
        self.set_interval(3.0, self.refresh_data)

    def refresh_data(self) -> None:
        """Pull counts from the DB and re-render the summary."""
        if not self.visible:
            return
        try:
            db = self.app.db  # type: ignore[attr-defined]
            content = self.query_one("#overview-content", Static)

            session_rows = db.fetchall(
                "SELECT status FROM sessions WHERE deleted_at IS NULL"
            )
            run_rows = db.fetchall("SELECT status FROM runs ORDER BY created_at DESC LIMIT 8")
            task_rows = db.fetchall(
                "SELECT status FROM tasks WHERE deleted_at IS NULL"
            )
            auto_rows = db.fetchall("SELECT enabled FROM automations")
            msg_row = db.fetchone(
                "SELECT COUNT(*) c FROM messages WHERE claimed_at IS NULL"
            )
            know_row = db.fetchone("SELECT COUNT(*) c FROM knowledge_artifacts")
            recent_events = db.fetchall(
                "SELECT * FROM events ORDER BY timestamp DESC LIMIT 8"
            )

            unclaimed = msg_row["c"] if msg_row else 0
            artifacts = know_row["c"] if know_row else 0

            from ..relay.mqtt_relay import RelayConfig
            relay = RelayConfig(db)
            relay_state = "enabled" if relay.enabled else "disabled"

            text = Text()

            # ── Status grid ────────────────────────────────────────────────
            text.append("  STATUS\n", style=f"bold {theme.ACCENT_HI}")
            text.append("  " + "─" * 50 + "\n\n", style=f"dim {theme.TEXT_FAINT}")

            active = sum(1 for r in session_rows if (r["status"] or "") in ("active", "working", "running"))
            text.append("  Sessions     ", style=f"bold {theme.TEXT_DIM}")
            text.append(f"● {active} active", style=f"bold {theme.GREEN}")
            text.append(f" · {len(session_rows)} total\n", style=f"dim {theme.TEXT_FAINT}")

            running = sum(1 for r in run_rows if r["status"] == "running")
            done = sum(1 for r in run_rows if r["status"] in ("completed", "failed"))
            text.append("  Runs         ", style=f"bold {theme.TEXT_DIM}")
            text.append(f"⟳ {running} running", style=f"bold {theme.CYAN}")
            text.append(f" · {done} finished\n", style=f"dim {theme.TEXT_FAINT}")

            todo = sum(1 for r in task_rows if r["status"] == "todo")
            wip = sum(1 for r in task_rows if r["status"] == "in_progress")
            done_t = sum(1 for r in task_rows if r["status"] == "done")
            text.append("  Tasks        ", style=f"bold {theme.TEXT_DIM}")
            text.append(f"{done_t} done", style=f"bold {theme.GREEN}")
            text.append(f" · {wip} in-progress", style=f"bold {theme.YELLOW}")
            text.append(f" · {todo} todo\n", style=f"dim {theme.TEXT_FAINT}")

            enabled = sum(1 for r in auto_rows if r["enabled"])
            text.append("  Automations  ", style=f"bold {theme.TEXT_DIM}")
            text.append(f"⏱ {enabled} enabled", style=f"bold {theme.PURPLE}")
            text.append(f" · {len(auto_rows)} total\n", style=f"dim {theme.TEXT_FAINT}")

            text.append("  Mailbox      ", style=f"bold {theme.TEXT_DIM}")
            text.append(f"📬 {unclaimed} unclaimed", style=f"bold {theme.PINK}")
            text.append("\n")

            text.append("  Knowledge    ", style=f"bold {theme.TEXT_DIM}")
            text.append(f"🧠 {artifacts} artifacts", style=f"bold {theme.CYAN}")
            text.append("\n")

            relay_color = theme.GREEN if relay_state == "enabled" else theme.TEXT_DIM
            text.append("  Relay        ", style=f"bold {theme.TEXT_DIM}")
            text.append(f"⇄ {relay_state}", style=f"bold {relay_color}")
            text.append("\n\n")

            # ── System health ──────────────────────────────────────────────
            text.append("  SYSTEM\n", style=f"bold {theme.ACCENT_HI}")
            text.append("  " + "─" * 50 + "\n", style=f"dim {theme.EDGE}")

            # Config validation
            try:
                from ...core.config import SynapseConfig as _Cfg

                issues = _Cfg.load().validate()
                if issues:
                    text.append("  Config       ", style=f"bold {theme.TEXT_DIM}")
                    text.append(f"⚠ {len(issues)} issue(s)\n", style=f"bold {theme.YELLOW}")
                else:
                    text.append("  Config       ", style=f"bold {theme.TEXT_DIM}")
                    text.append("✓ valid\n", style=f"bold {theme.GREEN}")
            except Exception:
                pass

            # Hooks installed
            try:
                from ...hooks.registry import HookInstaller

                installed = HookInstaller().verify_claude_hooks()
                text.append("  Hooks        ", style=f"bold {theme.TEXT_DIM}")
                if installed:
                    text.append("● claude hooks installed\n", style=f"bold {theme.GREEN}")
                else:
                    text.append("○ not installed (see Hooks panel)\n", style=f"dim {theme.TEXT_FAINT}")
            except Exception:
                pass

            # Environment / API keys
            import os as _os

            keys = [k for k in ("ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY") if _os.environ.get(k)]
            text.append("  API keys     ", style=f"bold {theme.TEXT_DIM}")
            if keys:
                text.append(f"● {len(keys)} configured\n", style=f"bold {theme.GREEN}")
            else:
                text.append("○ none — orchestration uses session agents\n", style=f"dim {theme.TEXT_FAINT}")
            text.append("\n")

            # ── Recent runs ────────────────────────────────────────────────
            text.append("  RECENT RUNS\n", style=f"bold {theme.ACCENT_HI}")
            text.append("  " + "─" * 50 + "\n", style=f"dim {theme.TEXT_FAINT}")
            if run_rows:
                for r in run_rows[:4]:
                    status = (r["status"] or "?").lower()
                    color = theme.STATUS_FG.get(status, theme.TEXT_DIM)
                    text.append(f"  {r['id'][:8]}", style=f"dim {theme.TEXT_FAINT}")
                    text.append(f"  [{status}]", style=f"bold {color}")
                    text.append(f"  {(r['mode'] or '?').upper():<10}", style=f"bold {theme.CYAN}")
                    text.append(f"  {(r['goal'] or '')[:34]}\n", style=f"dim {theme.TEXT_DIM}")
            else:
                text.append("  No runs yet.\n", style="dim italic")
            text.append("\n")

            # ── Recent activity ────────────────────────────────────────────
            text.append("  RECENT ACTIVITY\n", style=f"bold {theme.ACCENT_HI}")
            text.append("  " + "─" * 50 + "\n", style=f"dim {theme.TEXT_FAINT}")
            if recent_events:
                for ev in recent_events:
                    ts = _ts_str(ev["timestamp"])
                    ev_type = ev["type"] or "?"
                    color = {
                        "message": theme.PINK,
                        "status": theme.YELLOW,
                        "life": theme.CYAN,
                        "file_edit": theme.YELLOW,
                        "tool_call": theme.CYAN,
                    }.get(ev_type, theme.TEXT_DIM)
                    sid = (ev["session_id"] or "?")[:8]
                    text.append(f"  [{ts}]", style=f"dim {theme.TEXT_FAINT}")
                    text.append(f" {sid}", style=f"dim {theme.CYAN}")
                    text.append(f" {ev_type:<10}", style=f"bold {color}")
                    import json as _json
                    try:
                        data = _json.loads(ev["data"] or "{}")
                        summary = (
                            data.get("body")
                            or data.get("file_path")
                            or data.get("tool")
                            or data.get("status")
                            or str(data)
                        )
                    except Exception:
                        summary = str(ev["data"])[:40]
                    text.append(f" {str(summary)[:40]}\n", style=f"dim {theme.TEXT_DIM}")
            else:
                text.append("  No activity yet.\n", style="dim italic")

            content.update(text)
        except Exception:
            pass