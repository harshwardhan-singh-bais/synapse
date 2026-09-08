"""
Synapse TUI — the main terminal user interface.
Built with Textual for rich, reactive terminal rendering.

Panels:
- Overview      (⌂) control centre — every subsystem at a glance
- Sessions      (⚡) live session list + terminal capture
- Runs          (⟳) orchestration dashboard
- Mailbox       (📬) inter-session messages
- Tasks         (✓) task board
- Automations   (⏱) scheduled jobs + history
- Knowledge     (🧠) knowledge artifacts
- Transcripts   (⇬) conversation transcripts (Claude/Gemini/Codex/Cursor/…)
- Hooks         (⛓) per-tool hook install/verify/remove
- Relay         (⇄) cross-device relay
- Activity      (📡) event stream
- System        (⚙) config, agents, plugins, scripts, workspaces

A command bar (slash commands) and a help overlay (?) expose every feature.
"""
from __future__ import annotations

import asyncio
import os
import threading
import time
from pathlib import Path
from typing import Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    Footer,
    Input,
    Label,
    Static,
    TabbedContent,
    TabPane,
)

from ..core.config import SynapseConfig
from ..core.paths import ensure_dirs
from ..db.database import Database
from .screens.new_artifact_screen import NewArtifactScreen
from .screens.new_automation_screen import NewAutomationScreen
from .screens.new_session_screen import NewSessionScreen
from .screens.confirm_screen import ConfirmScreen
from .screens.help_overlay import HelpOverlay
from .screens.new_task_screen import NewTaskScreen
from .screens.orchestrate_screen import OrchestrateScreen
from .widgets.activity_feed import ActivityFeed
from .widgets.agent_mailbox import AgentMailbox
from .widgets.automation_panel import AutomationPanel
from .widgets.command_bar import CommandBar
from .widgets.header_bar import SynapseHeader
from .widgets.hooks_panel import HooksPanel
from .widgets.knowledge_panel import KnowledgePanel
from .widgets.loaders import BootScreen, LoaderShowcaseScreen
from .widgets.orchestration_dashboard import OrchestrationDashboard
from .widgets.overview_panel import OverviewPanel
from .widgets.relay_panel import RelayPanel
from .widgets.session_sidebar import SessionSidebar
from .widgets.session_terminal import SessionTerminal
from .widgets.system_panel import SystemPanel
from .widgets.task_board import TaskBoard
from .widgets.transcript_panel import TranscriptPanel


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
            "  [bold #ffd166]⚡ PERF HUD[/]",
            "  [dim #5f566c]────────────────────────[/]",
            f"  [dim #968ba2]Sessions:[/]    [bold #5fd4ff]{self._session_count}[/]",
            f"  [dim #968ba2]Active Runs:[/] [bold #3ddc97]{self._run_count}[/]",
            f"  [dim #968ba2]Messages:[/]    [bold #ff5d8f]{self._message_count}[/]",
            f"  [dim #968ba2]Uptime:[/]      [bold #c792ea]{hours:02d}:{mins:02d}:{secs:02d}[/]",
            "  [dim #5f566c]────────────────────────[/]",
            "  [dim #5f566c]Press F6 to close[/]",
        ]
        self.update("\n".join(lines))


class SynapseApp(App):
    """Main Synapse TUI application."""

    CSS_PATH = Path(__file__).parent / "synapse.tcss"
    TITLE = "Synapse"
    SUB_TITLE = "unified agent orchestration"
    MOUSE_CONTROL = True  # Enable mouse support

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("n", "new_session", "New Session", show=True),
        Binding("o", "launch_orchestration", "Orchestrate", show=True),
        Binding("t", "new_task", "New Task", show=True),
        Binding("a", "new_automation", "New Auto", show=True),
        Binding("k", "new_artifact", "New Artifact", show=True),
        Binding("m", "compose_message", "Message", show=True),
        Binding("d", "delete_session", "Delete", show=True),
        Binding("r", "restart_session", "Restart", show=True),
        Binding("f", "fork_session", "Fork", show=True),
        Binding("s", "signal_session", "Signal", show=True),
        Binding("x", "attach_session", "Attach", show=True),
        Binding("1", "show_tab('overview')", "Overview", show=True),
        Binding("2", "show_tab('sessions')", "Sessions", show=True),
        Binding("3", "show_tab('orchestration')", "Runs", show=True),
        Binding("4", "show_tab('mailbox')", "Mailbox", show=True),
        Binding("5", "show_tab('tasks')", "Tasks", show=True),
        Binding("6", "show_tab('automations')", "Autos", show=True),
        Binding("7", "show_tab('knowledge')", "Know", show=True),
        Binding("8", "show_tab('transcripts')", "Transcripts", show=True),
        Binding("9", "show_tab('hooks')", "Hooks", show=True),
        Binding("0", "show_tab('system')", "System", show=True),
        Binding("question_mark", "help", "Help", show=True),
        Binding("ctrl+p", "focus_cmd", "Command bar", show=True),
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
        self._notifier = self._make_notifier()

    @staticmethod
    def _make_notifier():
        """Best-effort OS notifier; disabled if the platform lacks support."""
        try:
            from ..notifications.notifier import Notifier

            return Notifier(enabled=True, suppress_for_active=True, min_interval_secs=30)
        except Exception:
            return None

    def _os_notify(self, title: str, message: str, category: str = "general") -> None:
        """Fire an OS-level notification (rate-suppressed), never raising."""
        if self._notifier is None:
            return
        try:
            self._notifier.notify(title, message, category=category)
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────────────
    # Layout
    # ─────────────────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield SynapseHeader(
            self.config.db_path,
            default_agent=self.config.default_agent,
            id="app-header",
        )

        with Horizontal(id="app-layout"):
            # Left sidebar
            yield SessionSidebar(id="sidebar")

            # Main content
            with Vertical(id="main-content"):
                with TabbedContent(id="main-tabs", initial="overview"):
                    with TabPane("  ⌂ Overview  ", id="overview"):
                        yield OverviewPanel(id="overview-panel")

                    with TabPane("  ⚡ Sessions  ", id="sessions"):
                        yield SessionTerminal(id="session-terminal")

                    with TabPane("  ⟳ Runs  ", id="orchestration"):
                        yield OrchestrationDashboard(id="orch-dashboard")

                    with TabPane("  📬 Mailbox  ", id="mailbox"):
                        yield AgentMailbox(id="agent-mailbox")

                    with TabPane("  ✓ Tasks  ", id="tasks"):
                        yield TaskBoard(id="task-board")

                    with TabPane("  ⏱ Autos  ", id="automations"):
                        yield AutomationPanel(id="automation-panel")

                    with TabPane("  🧠 Knowledge  ", id="knowledge"):
                        yield KnowledgePanel(id="knowledge-panel")

                    with TabPane("  ⇬ Transcripts  ", id="transcripts"):
                        yield TranscriptPanel(id="transcript-panel")

                    with TabPane("  ⛓ Hooks  ", id="hooks"):
                        yield HooksPanel(id="hooks-panel")

                    with TabPane("  ⇄ Relay  ", id="relay"):
                        yield RelayPanel(id="relay-panel")

                    with TabPane("  📡 Activity  ", id="activity"):
                        yield ActivityFeed(id="activity-feed")

                    with TabPane("  ⚙ System  ", id="system"):
                        yield SystemPanel(id="system-panel")

        yield PerfHUD(id="perf-hud")
        yield CommandBar(id="command-bar")
        yield Footer()

    # ─────────────────────────────────────────────────────────────────────────
    # Lifecycle
    # ─────────────────────────────────────────────────────────────────────────

    def on_mount(self) -> None:
        # ASCII boot sequence: show once, then the main screen settles in.
        self.push_screen(BootScreen())
        self.set_timer(3.4, self._post_boot)
        # Poll for new collisions and completed runs
        self.set_interval(5.0, self._poll_alerts)

    def _post_boot(self) -> None:
        if isinstance(self.screen, BootScreen):
            self.pop_screen()
        self.notify(
            "Welcome to [bold #e89173]Synapse[/] — press [bold #d8b04c]?[/] for help, "
            "[bold #d8b04c]n[/] for a session, or type [bold #d8b04c]/help[/]",
            severity="information",
            timeout=4,
        )

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
                f"⚠ {body}",
                title="Collision Detected",
                severity="error",
                timeout=8,
            )
            self._os_notify("Synapse — collision detected", body, category="collision")

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
                glyph = "✓" if status == "completed" else "✗"
                self.notify(
                    f"{glyph} [{mode}] {run_id[:8]}  {status.upper()}\n{goal}",
                    title="Run Finished",
                    severity=severity,
                    timeout=6,
                )
                self._os_notify(
                    f"Synapse — run {status}",
                    f"[{mode}] {goal or run_id[:8]}",
                    category="runs",
                )

    # ─────────────────────────────────────────────────────────────────────────
    # Key / action handlers
    # ─────────────────────────────────────────────────────────────────────────

    async def action_new_session(self) -> None:
        """Open the new-session modal and create the session if confirmed."""
        self.run_worker(self._new_session_worker(), group="new-session", exclusive=True)

    async def _new_session_worker(self) -> None:
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
            self._os_notify("Synapse — session created", name, category="sessions")

            # Refresh sidebar immediately
            sidebar = self.query_one("#sidebar", SessionSidebar)
            sidebar.refresh_sessions()

        except Exception as exc:
            self.notify(
                f"Failed to create session:\n{exc}",
                severity="error",
                timeout=6,
            )

    async def action_new_task(self) -> None:
        """Open the new-task modal and create the task if confirmed."""
        self.run_worker(self._new_task_worker(), group="new-task", exclusive=True)

    async def _new_task_worker(self) -> None:
        result = await self.push_screen_wait(NewTaskScreen())
        if result is None:
            return

        title = result.get("title", "").strip()
        if not title:
            return

        try:
            now_ms = self.db.now_ms()
            self.db.execute(
                """
                INSERT INTO tasks (
                    title, description, status,
                    action_kind, action_target_session, action_repo_path,
                    action_worktree_branch, action_agent, action_command,
                    source, created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    title,
                    result.get("description"),
                    "todo",
                    result.get("action_kind"),
                    result.get("target_session"),
                    result.get("repo_path"),
                    result.get("branch"),
                    result.get("agent"),
                    result.get("command"),
                    "tui",
                    now_ms,
                    now_ms,
                ),
            )
            self.notify(f"✓ Task [bold]{title}[/] created.", severity="information", timeout=3)
            try:
                self.query_one("#task-board", TaskBoard).refresh_tasks()
            except Exception:
                pass
        except Exception as exc:
            self.notify(f"Failed to create task:\n{exc}", severity="error", timeout=5)

    async def action_new_automation(self) -> None:
        """Open the new-automation modal and create the automation if confirmed."""
        self.run_worker(self._new_automation_worker(), group="new-auto", exclusive=True)

    async def _new_automation_worker(self) -> None:
        result = await self.push_screen_wait(NewAutomationScreen())
        if result is None:
            return

        name = result.get("name", "").strip()
        trigger = result.get("trigger", "")
        if not name or not trigger:
            self.notify("Name and trigger are required.", severity="error", timeout=3)
            return

        try:
            from ...cli.commands.automation_cmds import _parse_trigger
            from ...automation.scheduler import AutomationScheduler
            from ...backend.tmux import TmuxBackend
            from ...session.manager import SessionManager

            scheduler = AutomationScheduler(
                self.db, SessionManager(self.db, TmuxBackend(), self.config)
            )
            schedule_kind, schedule_spec = _parse_trigger(trigger)
            next_run_at = scheduler.compute_initial_next_run(
                schedule_kind, schedule_spec, "UTC"
            )
            now_ms = self.db.now_ms()

            import uuid
            auto_id = str(uuid.uuid4())
            self.db.execute(
                """
                INSERT INTO automations (
                    id, name, enabled,
                    schedule_kind, schedule_spec, timezone,
                    action_kind, action_target_session, action_repo_path,
                    action_worktree_branch, action_agent, action_command,
                    prompt, next_run_at, created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    auto_id, name, 1,
                    schedule_kind, schedule_spec, "UTC",
                    result.get("action_kind"),
                    result.get("target_session"),
                    result.get("repo_path"),
                    result.get("branch"),
                    result.get("agent"),
                    result.get("command"),
                    result.get("prompt"),
                    next_run_at, now_ms, now_ms,
                ),
            )
            self.notify(
                f"⏱ Automation [bold]{name}[/] created  ({schedule_kind}={schedule_spec}).",
                severity="information",
                timeout=4,
            )
            try:
                self.query_one("#automation-panel", AutomationPanel).refresh_automations()
            except Exception:
                pass
        except Exception as exc:
            self.notify(f"Failed to create automation:\n{exc}", severity="error", timeout=6)

    async def action_new_artifact(self) -> None:
        """Open the new-artifact modal and write the artifact if confirmed."""
        self.run_worker(self._new_artifact_worker(), group="new-artifact", exclusive=True)

    async def _new_artifact_worker(self) -> None:
        result = await self.push_screen_wait(NewArtifactScreen())
        if result is None:
            return

        key = result.get("key", "").strip()
        if not key:
            return

        try:
            from ..knowledge.artifacts import ArtifactStore

            store = ArtifactStore(self.db)
            artifact = store.write(
                key,
                result.get("content") or "",
                name=result.get("name"),
                mime_type="text/plain",
            )
            self.notify(
                f"🧠 Artifact [bold]{key}[/] written  (id={artifact.id}).",
                severity="information",
                timeout=3,
            )
            try:
                self.query_one("#knowledge-panel", KnowledgePanel).refresh_artifacts()
            except Exception:
                pass
        except Exception as exc:
            self.notify(f"Failed to write artifact:\n{exc}", severity="error", timeout=5)

    async def action_launch_orchestration(self) -> None:
        """Open the orchestration modal and launch the run in a background thread."""
        self.run_worker(self._orchestrate_modal_worker(), group="orch-modal", exclusive=True)

    async def _orchestrate_modal_worker(self) -> None:
        result = await self.push_screen_wait(OrchestrateScreen())
        if result is None:
            return

        mode = result.get("mode", "goal")
        repo_path = result.get("repo_path") or str(Path.cwd())
        if not Path(repo_path).exists():
            self.notify(
                f"Repo path does not exist:\n{repo_path}",
                severity="error",
                timeout=5,
            )
            return

        self.notify(
            f"⟳ Launching {mode.upper()} run…\nwatch the Runs panel (key 3)",
            severity="information",
            timeout=5,
        )
        threading.Thread(
            target=self._orchestration_worker,
            args=(result, repo_path),
            daemon=True,
            name="synapse-orchestrate",
        ).start()

    def _orchestration_worker(self, result: dict, repo_path: str) -> None:
        """Run the orchestration engine off the UI thread (mirrors `synapse orchestrate`)."""
        mode = result.get("mode", "goal")
        goal = result.get("goal") or ""
        effort = result.get("effort") or "standard"
        team_name = result.get("team") or "full"

        try:
            from ..backend.tmux import TmuxBackend
            from ..orchestrator.engine import OrchestrationEngine
            from ..orchestrator.team_factory import load_team
            from ..orchestrator.types import Effort, GoalPlan, GoalStage, RunMode
            from ..session.manager import SessionManager

            session_mgr = SessionManager(self.db, TmuxBackend(), self.config)
            team = load_team(team_name)
            effort_enum = Effort(effort)

            has_api_key = any(
                os.environ.get(key)
                for key in ("GOOGLE_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY")
            )
            engine: OrchestrationEngine
            if has_api_key:
                try:
                    from ..orchestrator.api_orchestrator import ApiOrchestrator
                    engine = ApiOrchestrator(self.db, session_mgr, team, effort_enum, self.config)
                except ImportError:
                    engine = OrchestrationEngine(self.db, session_mgr, team, effort_enum, self.config)
            else:
                engine = OrchestrationEngine(self.db, session_mgr, team, effort_enum, self.config)

            plan: Optional[GoalPlan] = None
            run_mode = RunMode(mode)

            if mode == "test":
                from ..orchestrator.prompts import TEST_MODE_ORCHESTRATOR_PROMPT
                plan = GoalPlan(
                    context="Comprehensive software testing campaign.",
                    stages=[
                        GoalStage(1, "Setup & Discovery",
                                  "Understand the system: read the README, list endpoints/commands, identify key user flows.",
                                  verification="skip"),
                        GoalStage(2, "Feature Walkthroughs",
                                  "Exercise every documented feature. Run the test suite and document any failures."),
                        GoalStage(3, "Edge Cases",
                                  "Try unexpected inputs, missing data, concurrent operations, and error conditions."),
                        GoalStage(4, "Triage & Regression",
                                  "Summarise all findings in test-report.md. Create regression tests for every confirmed bug."),
                    ],
                )
                goal = TEST_MODE_ORCHESTRATOR_PROMPT
            elif mode == "improve":
                from ..orchestrator.prompts import IMPROVE_MODE_ORCHESTRATOR_PROMPT
                plan = GoalPlan(
                    context="Code quality improvement campaign.",
                    stages=[
                        GoalStage(1, "Simplification Analysis",
                                  "Find overly complex code that could be simplified without changing behaviour.",
                                  parallel_group=1, verification="skip"),
                        GoalStage(2, "Architecture Analysis",
                                  "Identify structural issues: tight coupling, missing abstractions, inconsistent patterns.",
                                  parallel_group=1, verification="skip"),
                        GoalStage(3, "Dead Weight Analysis",
                                  "Find unused code, dead imports, and commented-out blocks safe to remove.",
                                  parallel_group=1, verification="skip"),
                        GoalStage(4, "Security Analysis",
                                  "Identify obvious vulnerabilities: hardcoded secrets, injection vectors, missing validation.",
                                  parallel_group=1, verification="skip"),
                        GoalStage(5, "Triage & Fix",
                                  "Review all analysis reports. Apply safe fixes. Auto-commit each batch."),
                    ],
                )
                goal = IMPROVE_MODE_ORCHESTRATOR_PROMPT
            elif mode == "resume":
                row = self.db.fetchone(
                    "SELECT * FROM runs WHERE status IN ('running','paused','failed') "
                    "ORDER BY created_at DESC LIMIT 1"
                )
                if row is None:
                    self.call_from_thread(
                        self.notify, "No resumable run found.", severity="warning", timeout=4
                    )
                    return
                stored_run_id = row["id"]
                goal = row["goal"] or ""
                stage_rows = self.db.fetchall(
                    "SELECT * FROM stages WHERE run_id=? ORDER BY stage_index", (stored_run_id,)
                )
                pending = [
                    GoalStage(
                        index=s["stage_index"],
                        name=s["name"] or "",
                        description=s["description"] or "",
                        acceptance_criteria=s["acceptance_criteria"] or "",
                        parallel_group=s["parallel_group"],
                        verification=s["verification"] or "full",
                    )
                    for s in stage_rows
                    if s["status"] in ("pending", "running", "failed")
                ]
                if pending:
                    plan = GoalPlan(stages=pending)
                engine._run_id = stored_run_id

            result_obj = engine.run(
                goal=goal,
                repo_path=repo_path,
                plan=plan,
                mode=run_mode,
                require_clean_tree=False,
            )

            if result_obj.success:
                self.call_from_thread(
                    self.notify,
                    f"✓ Run completed: {result_obj.run_id[:8]}",
                    severity="information",
                    timeout=5,
                )
            else:
                self.call_from_thread(
                    self.notify,
                    f"✗ Run failed: {result_obj.error or 'unknown error'}",
                    severity="error",
                    timeout=6,
                )
        except Exception as exc:
            self.call_from_thread(
                self.notify, f"Orchestration error:\n{exc}", severity="error", timeout=6
            )
        finally:
            try:
                self.call_from_thread(
                    self.query_one("#orch-dashboard", OrchestrationDashboard).refresh_data
                )
            except Exception:
                pass

    async def action_delete_session(self) -> None:
        """Soft-delete the currently selected session (with confirmation)."""
        self.run_worker(self._delete_session_worker(), group="del-session", exclusive=True)

    async def _delete_session_worker(self) -> None:
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

        confirmed = await self.push_screen_wait(
            ConfirmScreen(
                "Delete Session",
                f"Soft-delete session [bold]{name}[/]?\n\nThe tmux window keeps running; "
                "the session is removed from Synapse.",
                confirm_label="Delete",
            )
        )
        if not confirmed:
            return

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

    async def action_fork_session(self) -> None:
        """Fork the selected session into a child (mirrors `synapse fork`)."""
        session_id = self._selected_session_id
        if session_id is None:
            self.notify("No session selected.", severity="warning", timeout=2)
            return
        try:
            import uuid as _uuid

            from ..backend.tmux import TmuxBackend
            from ..core.config import load_agents_toml
            from ..session.manager import SessionManager

            mgr = SessionManager(self.db, TmuxBackend(), self.config)
            parent = mgr.get_session(session_id) or mgr._resolve_session(session_id)
            if parent is None:
                self.notify("Session not found.", severity="error", timeout=3)
                return

            name = f"{parent.name}-fork"
            now = self.db.now_ms()
            child_id = str(_uuid.uuid4())

            agent_name = parent.agent or self.config.default_agent
            cwd = parent.cwd or "."
            agent_def = load_agents_toml().get(agent_name)
            if agent_def and agent_def.fork_args:
                cmd = agent_def.command or agent_name
                for arg in agent_def.fork_args:
                    cmd += " " + arg.replace("{id}", parent.agent_session_id or parent.id)
            elif agent_def and agent_def.resume_args:
                cmd = agent_def.command or agent_name
                for arg in agent_def.resume_args:
                    cmd += " " + arg.replace("{id}", parent.agent_session_id or parent.id)
            else:
                cmd = f"{agent_name} --resume {parent.agent_session_id or parent.id}"

            tmux = TmuxBackend()
            pane = tmux.new_window(
                session_name=f"synapse-{name}",
                window_name=child_id[:8],
                cwd=cwd,
                cmd=cmd,
            )
            backend_id = pane.pane_id or f"synapse-{name}:{child_id[:8]}"

            self.db.execute(
                """
                INSERT INTO sessions (
                    id, name, agent, backend_id, backend_type, cwd,
                    hook_state, status, parent_session_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'idle', 'active', ?, ?, ?)
                """,
                (child_id, name, agent_name, backend_id,
                 parent.backend_type or "local-tmux", cwd, parent.id, now, now),
            )
            self.notify(
                f"⑂ Forked [bold]{parent.name}[/] → [bold]{name}[/].",
                severity="information",
                timeout=3,
            )
            self.query_one("#sidebar", SessionSidebar).refresh_sessions()
        except Exception as exc:
            self.notify(f"Fork failed:\n{exc}", severity="error", timeout=5)

    async def action_signal_session(self) -> None:
        """Cycle the selected session's state: working → done → blocked → idle."""
        session_id = self._selected_session_id
        if session_id is None:
            self.notify("No session selected.", severity="warning", timeout=2)
            return
        states = ("working", "done", "blocked", "idle")
        try:
            row = self.db.fetchone(
                "SELECT hook_state, name FROM sessions WHERE id = ?", (session_id,)
            )
            current = (row["hook_state"] if row else None) or "idle"
            name = row["name"] if row else session_id[:8]
            nxt = states[(states.index(current) + 1) % len(states)]
            self.db.execute(
                "UPDATE sessions SET hook_state=?, hook_state_at=? WHERE id=?",
                (nxt, self.db.now_ms(), session_id),
            )
            self.notify(f"[bold]{name}[/] → {nxt}", severity="information", timeout=2)
            self.query_one("#sidebar", SessionSidebar).refresh_sessions()
        except Exception as exc:
            self.notify(f"Signal failed:\n{exc}", severity="error", timeout=4)

    async def action_attach_session(self) -> None:
        """Attach the selected session's tmux pane (suspends the TUI)."""
        session_id = self._selected_session_id
        if session_id is None:
            self.notify("No session selected.", severity="warning", timeout=2)
            return
        try:
            row = self.db.fetchone(
                "SELECT backend_id, name FROM sessions WHERE id = ?", (session_id,)
            )
            if not row or not row["backend_id"]:
                self.notify(
                    "Session has no tmux pane attached.", severity="warning", timeout=3
                )
                return
            backend_id = row["backend_id"]
            name = row["name"] or session_id[:8]
            self.notify(
                f"Attaching to [bold]{name}[/] — detach with Ctrl-b d.",
                severity="information",
                timeout=3,
            )
            await asyncio.sleep(0.4)
            with self.suspend():
                import subprocess as _sp

                _sp.run(["tmux", "-L", "synapse", "attach-session", "-t", backend_id])
        except FileNotFoundError:
            self.notify("tmux not found on PATH.", severity="error", timeout=4)
        except Exception as exc:
            self.notify(f"Attach failed:\n{exc}", severity="error", timeout=5)

    def action_compose_message(self) -> None:
        """Focus the command bar with a prefilled /send, or open the mailbox."""
        try:
            if self._selected_session_id:
                self.query_one("#cmd-input", Input).value = "/send "
                self.query_one("#cmd-input", Input).focus()
            else:
                self.query_one("#main-tabs", TabbedContent).active = "mailbox"
                self.query_one("#compose-input", Input).focus()
        except Exception:
            pass

    def action_show_tab(self, tab_name: str) -> None:
        """Switch to the named tab."""
        try:
            tabs = self.query_one("#main-tabs", TabbedContent)
            tabs.active = tab_name
        except Exception:
            pass

    def action_help(self) -> None:
        """Show the help overlay (also via /help)."""
        self.push_screen(HelpOverlay())

    async def action_focus_cmd(self) -> None:
        """Focus the command-bar input (ctrl+p)."""
        try:
            self.query_one("#cmd-input", Input).focus()
        except Exception:
            pass

    def action_refresh_all(self) -> None:
        """Force-refresh all panels."""
        for panel_id, method in (
            ("#sidebar", "refresh_sessions"),
            ("#session-terminal", "refresh_content"),
            ("#orch-dashboard", "refresh_data"),
            ("#agent-mailbox", "refresh_inbox"),
            ("#overview-panel", "refresh_data"),
            ("#task-board", "refresh_tasks"),
            ("#automation-panel", "refresh_automations"),
            ("#knowledge-panel", "refresh_artifacts"),
            ("#transcript-panel", "refresh_files"),
            ("#hooks-panel", "refresh_hooks"),
            ("#relay-panel", "refresh_relay"),
            ("#activity-feed", "refresh_feed"),
            ("#system-panel", "refresh_data"),
        ):
            try:
                widget = self.query_one(panel_id)
                getattr(widget, method)()
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

    def action_show_loader_showcase(self) -> None:
        """Open the ASCII loader showcase."""
        self.push_screen(LoaderShowcaseScreen())

    async def action_quit(self) -> None:
        """Exit Synapse TUI."""
        self.exit()

    # ─────────────────────────────────────────────────────────────────────────
    # Slash-command handlers (dispatched by the CommandBar)
    # ─────────────────────────────────────────────────────────────────────────

    def cmd_help(self, *_args) -> None:
        self.action_help()

    def cmd_new(self, name: str = "", *_rest) -> None:
        """/new [name] — create a session (modal if no name given)."""
        if not name:
            self.run_worker(self.action_new_session(), group="cmd-new", exclusive=True)
            return

        async def _run() -> None:
            await self._create_session_from(
                {"name": name, "repo_path": None, "agent": self.config.default_agent}
            )

        self.run_worker(_run(), group="cmd-new", exclusive=True)

    def cmd_orchestrate(self, *args) -> None:
        """/orchestrate [goal] — launch a goal run (modal if no goal)."""
        goal = " ".join(args).strip()

        async def _run() -> None:
            if not goal:
                await self.action_launch_orchestration()
                return
            repo = str(Path.cwd())
            if not Path(repo).exists():
                self.notify("CWD unavailable for orchestration.", severity="error", timeout=4)
                return
            self.notify(
                f"⟳ Launching GOAL run… watch the Runs panel (key 3)",
                severity="information",
                timeout=4,
            )
            threading.Thread(
                target=self._orchestration_worker,
                args=({"mode": "goal", "goal": goal, "effort": self.config.effort, "team": "full"}, repo),
                daemon=True,
                name="synapse-orchestrate",
            ).start()

        self.run_worker(_run(), group="cmd-orchestrate", exclusive=True)

    def cmd_task(self, *args) -> None:
        """/task <title> — quick-create a task (modal if no title)."""
        title = " ".join(args).strip()
        if not title:
            self.run_worker(self.action_new_task(), group="cmd-task", exclusive=True)
            return
        try:
            now_ms = self.db.now_ms()
            self.db.execute(
                "INSERT INTO tasks (title, status, source, created_at, updated_at) "
                "VALUES (?, 'todo', 'tui', ?, ?)",
                (title, now_ms, now_ms),
            )
            self.notify(f"✓ Task [bold]{title}[/] created.", severity="information", timeout=3)
            try:
                self.query_one("#task-board", TaskBoard).refresh_tasks()
            except Exception:
                pass
        except Exception as exc:
            self.notify(f"Failed to create task:\n{exc}", severity="error", timeout=5)

    def cmd_auto(self, name: str = "", *_rest) -> None:
        """/auto [name] — create a daily automation (modal if no name)."""
        if not name:
            self.run_worker(self.action_new_automation(), group="cmd-auto", exclusive=True)
            return

        async def _run() -> None:
            await self._create_automation_from(
                {"name": name, "trigger": "daily", "action_kind": "send"}
            )

        self.run_worker(_run(), group="cmd-auto", exclusive=True)

    def cmd_msg(self, target: str = "", *rest) -> None:
        """/msg <session> <text> — message a session by name or id prefix."""
        body = " ".join(rest).strip()
        if not target or not body:
            self.notify("Usage: /msg <session> <text>", severity="warning", timeout=3)
            return
        try:
            row = self.db.fetchone(
                "SELECT id FROM sessions WHERE (id LIKE ? OR name = ?) AND deleted_at IS NULL",
                (f"{target}%", target),
            )
            if not row:
                self.notify(f"Session '{target}' not found.", severity="error", timeout=3)
                return
            self.db.execute(
                "INSERT INTO messages (to_session_id, from_session_id, kind, body, intent, created_at) "
                "VALUES (?, 'tui', 'chat', ?, 'inform', ?)",
                (row["id"], body, self.db.now_ms()),
            )
            self.notify(f"Message → [bold]{target}[/].", severity="information", timeout=2)
        except Exception as exc:
            self.notify(str(exc), severity="error", timeout=4)

    def cmd_send(self, *args) -> None:
        """/send <text> — message the selected session."""
        body = " ".join(args).strip()
        if not body:
            self.notify("Usage: /send <text>", severity="warning", timeout=3)
            return
        if not self._selected_session_id:
            self.notify("No session selected.", severity="warning", timeout=3)
            return
        try:
            self.db.execute(
                "INSERT INTO messages (to_session_id, from_session_id, kind, body, intent, created_at) "
                "VALUES (?, 'tui', 'chat', ?, 'inform', ?)",
                (self._selected_session_id, body, self.db.now_ms()),
            )
            self.notify("Message sent.", severity="information", timeout=2)
            try:
                self.query_one("#agent-mailbox", AgentMailbox).refresh_inbox()
            except Exception:
                pass
        except Exception as exc:
            self.notify(str(exc), severity="error", timeout=4)

    def cmd_broadcast(self, *args) -> None:
        """/broadcast <text> — message every session."""
        body = " ".join(args).strip()
        if not body:
            self.notify("Usage: /broadcast <text>", severity="warning", timeout=3)
            return
        try:
            self.db.execute(
                "INSERT INTO messages (to_session_id, from_session_id, kind, body, intent, created_at) "
                "VALUES (NULL, 'tui', 'chat', ?, 'inform', ?)",
                (body, self.db.now_ms()),
            )
            self.notify("Broadcast sent.", severity="information", timeout=2)
        except Exception as exc:
            self.notify(str(exc), severity="error", timeout=4)

    def cmd_signal(self, state: str = "", *_rest) -> None:
        """/signal working|done|blocked|idle — set the selected session's state."""
        state = state.lower()
        if state not in ("working", "done", "blocked", "idle"):
            self.notify("Usage: /signal working|done|blocked|idle", severity="warning", timeout=3)
            return
        if not self._selected_session_id:
            self.notify("No session selected.", severity="warning", timeout=3)
            return
        try:
            self.db.execute(
                "UPDATE sessions SET hook_state=?, hook_state_at=? WHERE id=?",
                (state, self.db.now_ms(), self._selected_session_id),
            )
            self.notify(f"Signal → {state}.", severity="information", timeout=2)
            self.query_one("#sidebar", SessionSidebar).refresh_sessions()
        except Exception as exc:
            self.notify(str(exc), severity="error", timeout=4)

    def cmd_fork(self, *_args) -> None:
        """/fork — fork the selected session."""
        self.run_worker(self.action_fork_session(), group="cmd-fork", exclusive=True)

    def cmd_attach(self, *_args) -> None:
        """/attach — attach the selected session in tmux."""
        self.run_worker(self.action_attach_session(), group="cmd-attach", exclusive=True)

    def cmd_refresh(self, *_args) -> None:
        self.action_refresh_all()

    def cmd_quit(self, *_args) -> None:
        self.exit()

    # ─────────────────────────────────────────────────────────────────────────
    # Shared async creation helpers (used by both modals and slash commands)
    # ─────────────────────────────────────────────────────────────────────────

    async def _create_session_from(self, result: dict) -> None:
        name: str = (result.get("name") or "").strip()
        if not name:
            self.notify("Session name is required.", severity="error", timeout=3)
            return
        try:
            from ..backend.tmux import TmuxBackend
            from ..session.manager import SessionManager

            mgr = SessionManager(self.db, TmuxBackend(), self.config)
            repo_path = result.get("repo_path")
            resolved_repo = str(Path(repo_path).resolve()) if repo_path else str(Path.cwd())
            session = mgr.create_session(
                name=name,
                agent=result.get("agent") or self.config.default_agent,
                repo_path=resolved_repo,
                worktree_branch=result.get("worktree_branch"),
            )
            self.notify(
                f"⚡ Session [bold]{session.name}[/] created  ·  {session.id[:8]}",
                severity="information",
                timeout=4,
            )
            self.query_one("#sidebar", SessionSidebar).refresh_sessions()
        except Exception as exc:
            self.notify(f"Failed to create session:\n{exc}", severity="error", timeout=6)

    async def _create_automation_from(self, result: dict) -> None:
        try:
            from ...automation.scheduler import AutomationScheduler
            from ...backend.tmux import TmuxBackend
            from ...cli.commands.automation_cmds import _parse_trigger
            from ...session.manager import SessionManager

            scheduler = AutomationScheduler(
                self.db, SessionManager(self.db, TmuxBackend(), self.config)
            )
            schedule_kind, schedule_spec = _parse_trigger(result.get("trigger", "daily"))
            next_run_at = scheduler.compute_initial_next_run(schedule_kind, schedule_spec, "UTC")
            now_ms = self.db.now_ms()
            import uuid as _uuid

            self.db.execute(
                """
                INSERT INTO automations (
                    id, name, enabled, schedule_kind, schedule_spec, timezone,
                    action_kind, action_target_session, action_repo_path,
                    action_worktree_branch, action_agent, action_command,
                    prompt, next_run_at, created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    str(_uuid.uuid4()), result.get("name", "automation"), 1,
                    schedule_kind, schedule_spec, "UTC",
                    result.get("action_kind"), result.get("target_session"),
                    result.get("repo_path"), result.get("branch"),
                    result.get("agent"), result.get("command"), result.get("prompt"),
                    next_run_at, now_ms, now_ms,
                ),
            )
            self.notify(
                f"⏱ Automation [bold]{result.get('name')}[/] created.",
                severity="information",
                timeout=4,
            )
            try:
                self.query_one("#automation-panel", AutomationPanel).refresh_automations()
            except Exception:
                pass
        except Exception as exc:
            self.notify(f"Failed to create automation:\n{exc}", severity="error", timeout=6)

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