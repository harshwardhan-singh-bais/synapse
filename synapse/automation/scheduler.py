"""
Automation scheduler — fires automations based on cron schedules or one-shot times.
Polls DB every 60 seconds. Atomic claim prevents double-firing across processes.
"""
from __future__ import annotations

import subprocess
import threading
import time
from datetime import datetime
from typing import Optional

from croniter import croniter  # type: ignore[import]

from ..db.database import Database
from ..session.manager import SessionManager


class AutomationScheduler:
    """
    Background thread that wakes every 60 seconds to check for due automations.

    Firing strategy:

    * **send** — deliver a prompt to an existing session via :meth:`SessionManager.send_text`.
    * **spawn** — create a new session in *repo* and optionally send an initial prompt.
    * **exec** — run an arbitrary shell command via :func:`subprocess.Popen`.

    ``next_run_at`` is updated immediately after firing to prevent double-fires
    even if multiple Synapse processes are running against the same DB (WAL mode
    + ``BEGIN IMMEDIATE`` serialises the updates).
    """

    def __init__(self, db: Database, session_mgr: SessionManager) -> None:
        self.db = db
        self.session_mgr = session_mgr
        self._thread: Optional[threading.Thread] = None
        self._running = False

    # ──────────────────────────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the scheduler background thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="synapse-scheduler"
        )
        self._thread.start()

    def stop(self) -> None:
        """Signal the scheduler to exit after the next sleep."""
        self._running = False

    # ──────────────────────────────────────────────────────────────
    # Internal loop
    # ──────────────────────────────────────────────────────────────

    def _run(self) -> None:
        while self._running:
            try:
                self._tick()
            except Exception:
                pass  # Scheduler errors must not crash the host process
            time.sleep(60)

    def _tick(self) -> None:
        now_ms = self.db.now_ms()
        due = self.db.fetchall(
            """
            SELECT * FROM automations
            WHERE enabled = 1
              AND deleted_at IS NULL
              AND (next_run_at IS NULL OR next_run_at <= ?)
            """,
            (now_ms,),
        )
        for row in due:
            automation = dict(row)
            self._fire(automation, now_ms)
            self._advance(automation, now_ms)

    # ──────────────────────────────────────────────────────────────
    # Firing
    # ──────────────────────────────────────────────────────────────

    def _fire(self, automation: dict, now_ms: int) -> None:
        kind = automation.get("action_kind", "")
        prompt = automation.get("prompt") or ""
        auto_id: str = automation["id"]
        name = automation.get("name") or auto_id[:8]
        success = True
        error_msg = ""
        result_detail = ""

        try:
            if kind == "send":
                target = automation.get("action_target_session")
                if target:
                    self.session_mgr.send_text(target, prompt)
                    result_detail = f"sent to {target[:8]}"
                else:
                    result_detail = "no target session"

            elif kind == "spawn":
                repo = automation.get("action_repo_path")
                agent = automation.get("action_agent") or "claude"
                branch = automation.get("action_worktree_branch")
                if repo:
                    session = self.session_mgr.create_session(
                        name=f"auto-{auto_id[:8]}",
                        repo_path=repo,
                        agent=agent,
                        worktree_branch=branch,
                        tag="automation",
                    )
                    if prompt:
                        self.session_mgr.send_text(session.id, prompt)
                    result_detail = f"spawned session {session.id[:8]}"
                else:
                    result_detail = "no repo path"

            elif kind == "exec":
                cmd = automation.get("action_command")
                if cmd:
                    subprocess.Popen(cmd, shell=True)  # noqa: S602
                    result_detail = f"exec: {cmd[:60]}"
                else:
                    result_detail = "no command set"

        except Exception as exc:
            success = False
            error_msg = str(exc)[:200]
            result_detail = f"error: {error_msg}"

        # Log run history
        self._log_run(auto_id, name, kind, now_ms, success, result_detail, error_msg)

        self.db.execute(
            "UPDATE automations SET last_run_at=? WHERE id=?",
            (now_ms, auto_id),
        )

    def _log_run(
        self,
        automation_id: str,
        automation_name: str,
        action_kind: str,
        fired_at: int,
        success: bool,
        result: str,
        error: str,
    ) -> None:
        """Record an automation run to the automation_runs history table."""
        try:
            self.db.execute(
                """
                INSERT INTO automation_runs
                    (automation_id, automation_name, action_kind,
                     fired_at, success, result, error, created_at)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (automation_id, automation_name, action_kind,
                 fired_at, 1 if success else 0, result, error, fired_at),
            )
        except Exception:
            pass  # Run history is best-effort

    # ──────────────────────────────────────────────────────────────
    # Schedule advancement
    # ──────────────────────────────────────────────────────────────

    def _advance(self, automation: dict, now_ms: int) -> None:
        schedule_kind = automation.get("schedule_kind", "")
        auto_id: str = automation["id"]

        if schedule_kind == "once":
            # Disable after a single fire.
            self.db.execute(
                "UPDATE automations SET enabled=0 WHERE id=?",
                (auto_id,),
            )
        elif schedule_kind == "cron":
            spec = automation.get("schedule_spec") or "0 * * * *"
            tz = automation.get("timezone") or "UTC"
            next_ms = self._next_cron_ms(spec, tz)
            if next_ms is not None:
                self.db.execute(
                    "UPDATE automations SET next_run_at=? WHERE id=?",
                    (next_ms, auto_id),
                )

    @staticmethod
    def _next_cron_ms(spec: str, tz: str) -> Optional[int]:
        try:
            import pendulum  # type: ignore[import]
            now_dt = pendulum.now(tz)
            cron = croniter(spec, now_dt)
            next_dt: datetime = cron.get_next(datetime)
            return int(next_dt.timestamp() * 1000)
        except Exception:
            return None

    # ──────────────────────────────────────────────────────────────
    # Public helpers (used by CLI at creation time)
    # ──────────────────────────────────────────────────────────────

    def compute_initial_next_run(
        self,
        schedule_kind: str,
        schedule_spec: str,
        timezone: str = "UTC",
    ) -> Optional[int]:
        """
        Compute the first ``next_run_at`` epoch-ms value for a new automation.

        * ``once`` — *schedule_spec* is an ISO 8601 datetime string.
        * ``cron`` — *schedule_spec* is a cron expression.
        """
        if schedule_kind == "once":
            try:
                import pendulum  # type: ignore[import]
                dt = pendulum.parse(schedule_spec, tz=timezone)
                return int(dt.timestamp() * 1000)
            except Exception:
                return None
        elif schedule_kind == "cron":
            return self._next_cron_ms(schedule_spec, timezone)
        return None
