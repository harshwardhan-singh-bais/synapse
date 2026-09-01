"""
Synapse TUI — the main terminal user interface.
Built with Textual for rich, reactive terminal rendering.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    Footer,
    Header,
    Label,
    Static,
    TabbedContent,
    TabPane,
)

from ..core.config import SynapseConfig
from ..core.paths import ensure_dirs
from ..db.database import Database
from .screens.new_session_screen import NewSessionScreen
from .widgets.agent_mailbox import AgentMailbox
from .widgets.orchestration_dashboard import OrchestrationDashboard
from .widgets.session_sidebar import SessionSidebar
from .widgets.session_terminal import SessionTerminal


# ─────────────────────────────────────────────────────────────────────────────
# Status bar widget
# ─────────────────────────────────────────────────────────────────────────────

class StatusBar(Static):
    """Bottom status bar showing DB path, session count, and clock."""

    DEFAULT_CSS = """
    StatusBar {
        background: #0d1117;
        color: #484f58;
        height: 1;
        padding: 0 1;
        dock: bottom;
        border-top: solid #21262d;
    }
    """

    def __init__(self, db_path: Path, **kwargs) -> None:
        super().__init__(**kwargs)
        self._db_path = db_path

    def on_mount(self) -> None:
        self.set_interval(1.0, self._tick)
        self._tick()

    def _tick(self) -> None:
        try:
            db = self.app.db  # type: ignore[attr-defined]
            session_count = db.fetchone(
                "SELECT COUNT(*) as c FROM sessions WHERE deleted_at IS NULL"
            )
            run_count = db.fetchone(
                "SELECT COUNT(*) as c FROM runs WHERE status = 'running'"
            )
            sessions = session_count["c"] if session_count else 0
            runs = run_count["c"] if run_count else 0
        except Exception:
            sessions, runs = 0, 0

        clock = time.strftime("%H:%M:%S")
        db_short = str(self._db_path).replace(str(Path.home()), "~")
        self.update(
            f" ⚡ Synapse  "
            f"│  sessions: {sessions}  "
            f"│  active runs: {runs}  "
            f"│  db: {db_short}  "
            f"│  {clock} "
        )


# ─────────────────────────────────────────────────────────────────────────────
# Main Application
# ─────────────────────────────────────────────────────────────────────────────

class PerfHUD(Static):
    """Performance HUD overlay showing real-time metrics."""

    DEFAULT_CSS = """
    #perf-hud {
        background: rgba(13, 17, 23, 0.9);
        border: solid #30363d;
        color: #8b949e;
        dock: right;
        width: 32;
        height: auto;
        max-height: 50%;
        padding: 1;
        layer: overlay;
        visibility: hidden;
    }
    #perf-hud.visible {
        visibility: visible;
    }
    .perf-title {
        color: #d29922;
        text-style: bold;
        border-bottom: solid #21262d;
        margin-bottom: 1;
    }
    .perf-row {
        color: #8b949e;
        height: 1;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._visible = False
        self._start_time = time.time()
        self._session_count = 0
        self._run_count = 0
        self._message_count = 0

    def on_mount(self) -> None:
        self.set_interval(2.0, self._tick)

    def toggle(self) -> None:
        """Toggle HUD visibility."""
        self._visible = not self._visible
        if self._visible:
            self.add_class("visible")
            self._tick()
        else:
            self.remove_class("visible")

    def _tick(self) -> None:
        if not self._visible:
            return
        try:
            db = self.app.db  # type: ignore[attr-defined]
            row = db.fetchone("SELECT COUNT(*) as c FROM sessions WHERE deleted_at IS NULL")
            self._session_count = row["c"] if row else 0
            row = db.fetchone("SELECT COUNT(*) as c FROM runs WHERE status = 'running'")
            self._run_count = row["c"] if row else 0
            row = db.fetchone("SELECT COUNT(*) as c FROM messages")
            self._message_count = row["c"] if row else 0
        except Exception:
            pass

        elapsed = time.time() - self._start_time
        hours = int(elapsed // 3600)
        mins = int((elapsed % 3600) // 60)
        secs = int(elapsed % 60)

        lines = [
            "  ⚡ Perf HUD",
            "  ─────────────────",
            f"  Sessions:    {self._session_count}",
            f"  Active Runs: {self._run_count}",
            f"  Messages:    {self._message_count}",
            f"  Uptime:      {hours:02d}:{mins:02d}:{secs:02d}",
            "  ─────────────────",
            "  Press F6 to close",
        ]
        self.update("\n".join(lines))


class SynapseApp(App):
    """Main Synapse TUI application."""

    CSS_PATH = Path(__file__).parent / "synapse.tcss"
    TITLE = "⚡ Synapse"
    SUB_TITLE = "Unified Agent Orchestration"
    MOUSE_CONTROL = True  # Enable mouse support

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("n", "new_session", "New Session", show=True),
        Binding("d", "delete_session", "Delete", show=True),
        Binding("r", "restart_session", "Restart", show=True),
        Binding("m", "compose_message", "Message", show=True),
        Binding("o", "open_orchestrate", "Orchestrate", show=True),
        Binding("1", "show_tab('sessions')", "Sessions", show=True),
        Binding("2", "show_tab('orchestration')", "Runs", show=True),
        Binding("3", "show_tab('mailbox')", "Mailbox", show=True),
        Binding("tab", "focus_next", "Next Panel", show=False),
        Binding("shift+tab", "focus_previous", "Prev Panel", show=False),
        Binding("f5", "refresh_all", "Refresh", show=False),
        Binding("f6", "toggle_perf_hud", "Perf HUD", show=True),
    ]

    def __init__(self, config: SynapseConfig) -> None:
        super().__init__()
        self.config = config
        ensure_dirs()
        self.db = Database(config.db_path)
        self._selected_session_id: Optional[str] = None
        self._known_collision_ids: set[int] = set()
        self._known_run_ids: set[str] = set()

    # ─────────────────────────────────────────────────────────────────────────
    # Layout
    # ─────────────────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header()

        with Horizontal(id="app-layout"):
            # Left sidebar
            yield SessionSidebar(id="sidebar")

            # Main content
            with Vertical(id="main-content"):
                with TabbedContent(id="main-tabs", initial="sessions"):
                    with TabPane("  Sessions  ", id="sessions"):
                        yield SessionTerminal(id="session-terminal")

                    with TabPane("  Runs  ", id="orchestration"):
                        yield OrchestrationDashboard(id="orch-dashboard")

                    with TabPane("  Mailbox  ", id="mailbox"):
                        yield AgentMailbox(id="agent-mailbox")

        yield PerfHUD(id="perf-hud")
        yield StatusBar(self.config.db_path)
        yield Footer()

    # ─────────────────────────────────────────────────────────────────────────
    # Lifecycle
    # ─────────────────────────────────────────────────────────────────────────

    def on_mount(self) -> None:
        self.notify(
            "Welcome to Synapse ⚡  Press [bold]n[/] to create your first session.",
            severity="information",
            timeout=4,
        )
        # Poll for new collisions and completed runs
        self.set_interval(5.0, self._poll_alerts)

    # ─────────────────────────────────────────────────────────────────────────
    # Session selection (called by sidebar)
    # ─────────────────────────────────────────────────────────────────────────

    def on_session_selected(self, session_id: str) -> None:
        """Called by SessionSidebar when the user picks a session."""
        self._selected_session_id = session_id

        # Update the terminal view
        try:
            terminal = self.query_one("#session-terminal", SessionTerminal)
            terminal.session_id = session_id
        except Exception:
            pass

        # Update the mailbox
        try:
            mailbox = self.query_one("#agent-mailbox", AgentMailbox)
            mailbox.session_id = session_id
        except Exception:
            pass

        # Fetch session name for a nice notification
        try:
            row = self.db.fetchone(
                "SELECT name, agent, status FROM sessions WHERE id = ?", (session_id,)
            )
            if row:
                name = row["name"]
                agent = row["agent"] or "?"
                status = row["status"] or "?"
                self.notify(
                    f"[bold]{name}[/]  ·  agent: {agent}  ·  status: {status}",
                    severity="information",
                    timeout=2,
                )
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────────────
    # Background alert polling
    # ─────────────────────────────────────────────────────────────────────────

    def _poll_alerts(self) -> None:
        """Check for new collisions and run state changes; show toasts."""
        try:
            self._check_collisions()
            self._check_runs()
        except Exception:
            pass

    def _check_collisions(self) -> None:
        rows = self.db.fetchall(
            """
            SELECT id, body, from_session_id, created_at
            FROM messages
            WHERE kind = 'collision'
            ORDER BY created_at DESC
            LIMIT 20
            """
        )
        for row in rows:
            msg_id = row["id"]
            if msg_id in self._known_collision_ids:
                continue
            self._known_collision_ids.add(msg_id)
            body = (row["body"] or "Collision detected")[:80]
            self.notify(
                f"⚠️  {body}",
                title="Collision Detected",
                severity="error",
                timeout=8,
            )

    def _check_runs(self) -> None:
        rows = self.db.fetchall(
            "SELECT id, mode, goal, status FROM runs ORDER BY created_at DESC LIMIT 20"
        )
        for row in rows:
            run_id = row["id"]
            status = row["status"] or ""
            key = f"{run_id}:{status}"

            if key in self._known_run_ids:
                continue
            self._known_run_ids.add(key)

            # Only notify on terminal states we haven't seen yet
            if status in ("completed", "failed"):
                mode = (row["mode"] or "run").upper()
                goal = (row["goal"] or "")[:50]
                severity = "information" if status == "completed" else "error"
                glyph = "✅" if status == "completed" else "❌"
                self.notify(
                    f"{glyph} [{mode}] {run_id[:8]}  {status.upper()}\n{goal}",
                    title="Run Finished",
                    severity=severity,
                    timeout=6,
                )

    # ─────────────────────────────────────────────────────────────────────────
    # Key / action handlers
    # ─────────────────────────────────────────────────────────────────────────

    async def action_new_session(self) -> None:
        """Open the new-session modal and create the session if confirmed."""
        result = await self.push_screen_wait(NewSessionScreen())
        if result is None:
            return

        name: str = result.get("name", "").strip()
        repo_path: Optional[str] = result.get("repo_path")
        agent: str = result.get("agent") or self.config.default_agent
        worktree_branch: Optional[str] = result.get("worktree_branch")

        if not name:
            self.notify("Session name is required.", severity="error", timeout=3)
            return

        try:
            from ..session.manager import SessionManager
            from ..backend.tmux import TmuxBackend

            mgr = SessionManager(self.db, TmuxBackend(), self.config)
            resolved_repo = str(Path(repo_path).resolve()) if repo_path else str(Path.cwd())
            session = mgr.create_session(
                name=name,
                agent=agent,
                repo_path=resolved_repo,
                worktree_branch=worktree_branch,
            )
            self.notify(
                f"⚡ Session [bold]{session.name}[/] created  ·  {session.id[:8]}",
                severity="information",
                timeout=4,
            )

            # Refresh sidebar immediately
            sidebar = self.query_one("#sidebar", SessionSidebar)
            sidebar.refresh_sessions()

        except Exception as exc:
            self.notify(
                f"Failed to create session:\n{exc}",
                severity="error",
                timeout=6,
            )

    async def action_delete_session(self) -> None:
        """Soft-delete the currently selected session."""
        session_id = self._selected_session_id
        if session_id is None:
            self.notify("No session selected.", severity="warning", timeout=2)
            return

        try:
            row = self.db.fetchone(
                "SELECT name FROM sessions WHERE id = ?", (session_id,)
            )
            name = row["name"] if row else session_id[:8]
        except Exception:
            name = session_id[:8]

        try:
            from ..session.manager import SessionManager
            from ..backend.tmux import TmuxBackend

            mgr = SessionManager(self.db, TmuxBackend(), self.config)
            mgr.delete_session(session_id)
            self._selected_session_id = None
            self.notify(
                f"Session [bold]{name}[/] deleted.",
                severity="warning",
                timeout=3,
            )
            sidebar = self.query_one("#sidebar", SessionSidebar)
            sidebar.selected_session_id = None
            sidebar.refresh_sessions()

            # Clear terminal
            terminal = self.query_one("#session-terminal", SessionTerminal)
            terminal.session_id = None

        except Exception as exc:
            self.notify(f"Delete failed:\n{exc}", severity="error", timeout=5)

    async def action_restart_session(self) -> None:
        """Restart the currently selected session."""
        session_id = self._selected_session_id
        if session_id is None:
            self.notify("No session selected.", severity="warning", timeout=2)
            return

        try:
            from ..session.manager import SessionManager
            from ..backend.tmux import TmuxBackend

            row = self.db.fetchone(
                "SELECT name FROM sessions WHERE id = ?", (session_id,)
            )
            name = row["name"] if row else session_id[:8]

            mgr = SessionManager(self.db, TmuxBackend(), self.config)
            mgr.restart_session(session_id)
            self.notify(
                f"⟳ Session [bold]{name}[/] restarted.",
                severity="information",
                timeout=3,
            )
            sidebar = self.query_one("#sidebar", SessionSidebar)
            sidebar.refresh_sessions()

        except Exception as exc:
            self.notify(f"Restart failed:\n{exc}", severity="error", timeout=5)

    def action_compose_message(self) -> None:
        """Focus the mailbox compose input."""
        try:
            tabs = self.query_one("#main-tabs", TabbedContent)
            tabs.active = "mailbox"
            mailbox = self.query_one("#agent-mailbox", AgentMailbox)
            mailbox.session_id = self._selected_session_id
            from textual.widgets import Input
            compose = self.query_one("#compose-input", Input)
            compose.focus()
        except Exception:
            pass

    def action_open_orchestrate(self) -> None:
        """Switch to the orchestration dashboard."""
        try:
            tabs = self.query_one("#main-tabs", TabbedContent)
            tabs.active = "orchestration"
        except Exception:
            pass

    def action_show_tab(self, tab_name: str) -> None:
        """Switch to the named tab."""
        try:
            tabs = self.query_one("#main-tabs", TabbedContent)
            tabs.active = tab_name
        except Exception:
            pass

    def action_refresh_all(self) -> None:
        """Force-refresh all panels."""
        try:
            self.query_one("#sidebar", SessionSidebar).refresh_sessions()
        except Exception:
            pass
        try:
            self.query_one("#session-terminal", SessionTerminal).refresh_content()
        except Exception:
            pass
        try:
            self.query_one("#orch-dashboard", OrchestrationDashboard).refresh_data()
        except Exception:
            pass
        try:
            self.query_one("#agent-mailbox", AgentMailbox).refresh_inbox()
        except Exception:
            pass
        self.notify("Refreshed.", severity="information", timeout=1)

    def action_toggle_perf_hud(self) -> None:
        """Toggle the performance HUD overlay."""
        try:
            hud = self.query_one("#perf-hud", PerfHUD)
            hud.toggle()
        except Exception:
            pass

    async def action_quit(self) -> None:
        """Exit Synapse TUI."""
        self.exit()

    # ─────────────────────────────────────────────────────────────────────────
    # Cleanup
    # ─────────────────────────────────────────────────────────────────────────

    def on_unmount(self) -> None:
        try:
            self.db.close()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def launch_tui(config: Optional[SynapseConfig] = None) -> None:
    """Construct and run the SynapseApp.

    Parameters
    ----------
    config:
        Loaded :class:`SynapseConfig`.  If *None*, loads from disk.
    """
    if config is None:
        config = SynapseConfig.load()
    ensure_dirs()
    app = SynapseApp(config)
    app.run()
