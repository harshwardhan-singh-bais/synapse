"""
SessionManager — all DB operations for sessions, worktrees, and messages.
All reads return models from synapse.session.models.
All writes are atomic SQLite transactions.
"""
from __future__ import annotations

import logging
import subprocess
import uuid
from pathlib import Path
from typing import Optional

from ..backend.tmux import TmuxBackend
from ..core.config import AgentDef, SynapseConfig
from ..core.paths import WORKTREES_DIR
from ..db.database import Database
from ..session.models import SessionInfo, SessionStatus, WorktreeInfo

log = logging.getLogger(__name__)


class SessionManager:
    """Facade over the DB + tmux backend for all session lifecycle operations."""

    def __init__(self, db: Database, tmux: TmuxBackend, config: SynapseConfig) -> None:
        self.db = db
        self.tmux = tmux
        self.config = config

    # ──────────────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────────────

    def _row_to_session(self, row: object) -> SessionInfo:
        return SessionInfo.model_validate(dict(row))  # type: ignore[call-overload, arg-type]

    def _now_ms(self) -> int:
        return self.db.now_ms()

    def _resolve_session(self, session_id: str) -> Optional[SessionInfo]:
        """Accept a full UUID or an 8-char prefix."""
        if len(session_id) == 36:
            return self.get_session(session_id)
        # Prefix match
        rows = self.db.fetchall(
            "SELECT * FROM sessions WHERE id LIKE ? AND deleted_at IS NULL",
            (f"{session_id}%",),
        )
        if len(rows) == 1:
            return self._row_to_session(rows[0])
        if len(rows) > 1:
            log.warning("Ambiguous session prefix '%s' — %d matches", session_id, len(rows))
        return None

    # ──────────────────────────────────────────────────────────────
    # Read operations
    # ──────────────────────────────────────────────────────────────

    def list_sessions(self, include_deleted: bool = False) -> list[SessionInfo]:
        """Return all sessions, optionally including soft-deleted ones."""
        if include_deleted:
            rows = self.db.fetchall(
                "SELECT * FROM sessions ORDER BY created_at DESC"
            )
        else:
            rows = self.db.fetchall(
                "SELECT * FROM sessions WHERE deleted_at IS NULL ORDER BY created_at DESC"
            )
        return [self._row_to_session(r) for r in rows]

    def get_session(self, session_id: str) -> Optional[SessionInfo]:
        """Return a session by exact UUID, or ``None`` if not found."""
        row = self.db.fetchone(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        )
        return self._row_to_session(row) if row else None

    def get_session_by_name(self, name: str) -> Optional[SessionInfo]:
        """Return the most recently created live session with *name*."""
        row = self.db.fetchone(
            """
            SELECT * FROM sessions
            WHERE name = ? AND deleted_at IS NULL
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (name,),
        )
        return self._row_to_session(row) if row else None

    def get_worktree(self, session_id: str) -> Optional[WorktreeInfo]:
        """Return the live worktree record for *session_id*, if any."""
        row = self.db.fetchone(
            """
            SELECT * FROM worktrees
            WHERE session_id = ? AND deleted_at IS NULL
            ORDER BY created_at DESC LIMIT 1
            """,
            (session_id,),
        )
        return WorktreeInfo.model_validate(dict(row)) if row else None  # type: ignore[call-overload, arg-type]

    # ──────────────────────────────────────────────────────────────
    # Create
    # ──────────────────────────────────────────────────────────────

    def _run_lifecycle_hooks(self, event: str, session_name: str = "", session_id: str = "") -> None:
        """Run thurbox hooks.toml lifecycle hooks (best-effort, non-blocking)."""
        try:
            from ..hooks.registry import run_lifecycle_hooks
            errors = run_lifecycle_hooks(event, session_name=session_name, session_id=session_id)
            for err in errors:
                log.warning("Lifecycle hook error for %s: %s", event, err)
        except Exception as exc:
            log.debug("Lifecycle hook dispatch failed for %s: %s", event, exc)

    def sync_from_remote(self, remote_url: str, remote_token: str) -> int:
        """Sync sessions from a remote Synapse instance.

        Fetches session state from a remote relay and merges it into the local DB.
        Returns the number of sessions synced.
        """
        import json
        import urllib.request

        synced = 0
        try:
            url = f"{remote_url.rstrip('/')}/api/sessions"
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {remote_token}"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())

            sessions = data if isinstance(data, list) else data.get("sessions", [])
            for remote_session in sessions:
                remote_id = remote_session.get("id")
                if not remote_id:
                    continue

                # Check if we already have this session
                existing = self.get_session(remote_id)
                if existing:
                    # Update status from remote
                    now = self._now_ms()
                    remote_status = remote_session.get("status")
                    if remote_status:
                        self.db.execute(
                            "UPDATE sessions SET status=?, updated_at=? WHERE id=?",
                            (remote_status, now, remote_id),
                        )
                    synced += 1
                else:
                    # Insert new session from remote
                    now = self._now_ms()
                    self.db.execute(
                        """
                        INSERT OR IGNORE INTO sessions
                            (id, name, agent, backend_id, backend_type, cwd,
                             hook_state, status, tag, parent_session_id,
                             created_at, updated_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            remote_id,
                            remote_session.get("name", f"remote-{remote_id[:8]}"),
                            remote_session.get("agent"),
                            remote_session.get("backend_id"),
                            remote_session.get("backend_type", "remote"),
                            remote_session.get("cwd"),
                            remote_session.get("hook_state"),
                            remote_session.get("status", "active"),
                            remote_session.get("tag", "remote"),
                            remote_session.get("parent_session_id"),
                            remote_session.get("created_at", now),
                            now,
                        ),
                    )
                    synced += 1

            log.info("Synced %d sessions from remote %s", synced, remote_url)
        except Exception as exc:
            log.error("Failed to sync from remote %s: %s", remote_url, exc)

        return synced

    def get_next_session_number(self, name_prefix: str = "session") -> int:
        """Return the next unique session number for a given name prefix.

        Queries the DB for the highest existing number matching the pattern
        ``<prefix>-<N>`` and returns N+1.  Returns 1 if no matches exist.
        """
        row = self.db.fetchone(
            """
            SELECT name FROM sessions
            WHERE name LIKE ? AND deleted_at IS NULL
            ORDER BY created_at DESC LIMIT 1
            """,
            (f"{name_prefix}-%",),
        )
        if row and row["name"]:
            parts = row["name"].rsplit("-", 1)
            if len(parts) == 2 and parts[1].isdigit():
                return int(parts[1]) + 1
        return 1

    def generate_unique_name(self, prefix: str = "session") -> str:
        """Generate a unique session name like ``session-1``, ``session-2``, etc."""
        num = self.get_next_session_number(prefix)
        return f"{prefix}-{num}"

    def create_session(
        self,
        name: str,
        repo_path: str,
        agent: str = "claude",
        worktree_branch: Optional[str] = None,
        base_branch: str = "main",
        tag: Optional[str] = None,
        parent_session_id: Optional[str] = None,
    ) -> SessionInfo:
        """Create a session: optionally git worktree → launch agent → persist to DB.

        Steps:
        1. Resolve agent definition from config (fall back to bare name as command).
        2. If ``worktree_branch`` is provided, create a git worktree and use its
           path as the working directory; otherwise use ``repo_path`` directly.
        3. Launch the agent command in a new tmux window.
        4. Insert the ``sessions`` row (and ``worktrees`` row if applicable).
        5. Return the populated :class:`SessionInfo`.
        """
        session_id = str(uuid.uuid4())
        now = self._now_ms()

        # 1. Resolve agent definition.
        agents = self.config.model_extra or {}
        agent_def: AgentDef = (
            agents.get(agent)  # type: ignore[assignment]
            or AgentDef(name=agent, command=agent)
        )
        # Re-check via load_agents_toml path if needed.
        from ..core.config import load_agents_toml
        agent_map = load_agents_toml()
        if agent in agent_map:
            agent_def = agent_map[agent]

        # 2. Set up working directory (and optional worktree).
        cwd = repo_path
        worktree_path_str: Optional[str] = None

        if worktree_branch:
            try:
                wt_path = self._create_worktree(repo_path, worktree_branch, base_branch)
                cwd = str(wt_path)
                worktree_path_str = cwd
                log.info("Worktree created at %s (branch: %s)", cwd, worktree_branch)
            except Exception as exc:
                log.error("Failed to create worktree for branch '%s': %s", worktree_branch, exc)
                raise

        # 3. Build and launch agent command in tmux.
        cmd = self._build_agent_command(agent_def, session_id, cwd)
        tmux_session_name = f"synapse-{name}"
        window_name = session_id[:8]

        pane = self.tmux.new_window(
            session_name=tmux_session_name,
            window_name=window_name,
            cwd=cwd,
            cmd=cmd,
        )

        backend_id = pane.pane_id or f"{tmux_session_name}:{window_name}"
        backend_type = agent_def.backend_type

        # 4. Persist to DB atomically.
        conn = self.db.connect()
        conn.execute("BEGIN")
        try:
            conn.execute(
                """
                INSERT INTO sessions (
                    id, name, agent, backend_id, backend_type,
                    cwd, hook_state, status, tag,
                    parent_session_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'idle', 'active', ?, ?, ?, ?)
                """,
                (
                    session_id, name, agent, backend_id, backend_type,
                    cwd, tag, parent_session_id, now, now,
                ),
            )

            if worktree_branch and worktree_path_str:
                conn.execute(
                    """
                    INSERT INTO worktrees
                        (session_id, repo_path, worktree_path, branch, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (session_id, repo_path, worktree_path_str, worktree_branch, now),
                )

            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            # Best-effort cleanup: kill the tmux window we already opened.
            if pane.pane_id:
                try:
                    self.tmux.kill_window(pane.pane_id)
                except Exception:
                    pass
            raise

        log.info("Session '%s' created (id=%s, agent=%s, pane=%s)", name, session_id, agent, backend_id)

        # Run post_create hooks
        self._run_lifecycle_hooks("post_create", session_name=name, session_id=session_id)

        result = self.get_session(session_id)
        assert result is not None
        return result

    # ──────────────────────────────────────────────────────────────
    # Delete / restart
    # ──────────────────────────────────────────────────────────────

    def delete_session(self, session_id: str, force: bool = False) -> bool:
        """Soft-delete a session (stamp ``deleted_at``).

        If *force* is ``True``, also kills the tmux window and removes the
        git worktree (hard delete).  The DB row is still retained with
        ``deleted_at`` set for audit purposes.
        """
        session = self._resolve_session(session_id)
        if session is None:
            log.warning("delete_session: session '%s' not found", session_id)
            return False

        # Run pre_delete hooks
        self._run_lifecycle_hooks("pre_delete", session_name=session.name or "", session_id=session.id)

        now = self._now_ms()

        if force:
            # Kill tmux window.
            if session.backend_id:
                try:
                    self.tmux.kill_window(session.backend_id)
                    log.debug("Killed tmux window %s", session.backend_id)
                except Exception as exc:
                    log.warning("Could not kill tmux window %s: %s", session.backend_id, exc)

            # Remove worktree.
            worktree = self.get_worktree(session.id)
            if worktree and worktree.worktree_path:
                try:
                    self._remove_worktree(worktree.worktree_path)
                    self.db.execute(
                        "UPDATE worktrees SET deleted_at = ? WHERE id = ?",
                        (now, worktree.id),
                    )
                    log.debug("Removed worktree %s", worktree.worktree_path)
                except Exception as exc:
                    log.warning("Could not remove worktree %s: %s", worktree.worktree_path, exc)

        self.db.execute(
            "UPDATE sessions SET deleted_at = ?, updated_at = ?, status = 'done' WHERE id = ?",
            (now, now, session.id),
        )
        log.info("Session '%s' deleted (force=%s)", session.id, force)

        # Run post_delete hooks
        self._run_lifecycle_hooks("post_delete", session_name=session.name or "", session_id=session.id)

        return True

    def restart_session(self, session_id: str) -> bool:
        """Kill and re-spawn the agent in the same tmux window.

        The pane/window IDs stay the same because we create a new window
        with the same coordinates and update the DB with the fresh pane ID.
        """
        session = self._resolve_session(session_id)
        if session is None:
            log.warning("restart_session: session '%s' not found", session_id)
            return False

        # Run pre_restart hooks
        self._run_lifecycle_hooks("pre_restart", session_name=session.name or "", session_id=session.id)

        # Kill existing window.
        if session.backend_id:
            try:
                self.tmux.kill_window(session.backend_id)
            except Exception as exc:
                log.warning("Could not kill window %s during restart: %s", session.backend_id, exc)

        # Re-derive launch parameters.
        from ..core.config import load_agents_toml
        agent_name = session.agent or self.config.default_agent
        agent_map = load_agents_toml()
        agent_def: AgentDef = agent_map.get(agent_name) or AgentDef(name=agent_name, command=agent_name)

        cwd = session.cwd or "."
        cmd = self._build_agent_command(agent_def, session.id, cwd)
        tmux_session_name = f"synapse-{session.name}"
        window_name = session.id[:8]

        try:
            pane = self.tmux.new_window(
                session_name=tmux_session_name,
                window_name=window_name,
                cwd=cwd,
                cmd=cmd,
            )
            new_backend_id = pane.pane_id or f"{tmux_session_name}:{window_name}"
        except Exception as exc:
            log.error("Failed to re-spawn agent for session %s: %s", session.id, exc)
            self.db.execute(
                "UPDATE sessions SET status = 'error', updated_at = ? WHERE id = ?",
                (self._now_ms(), session.id),
            )
            return False

        now = self._now_ms()
        self.db.execute(
            """
            UPDATE sessions
               SET backend_id = ?, status = 'active', hook_state = 'idle',
                   updated_at = ?
             WHERE id = ?
            """,
            (new_backend_id, now, session.id),
        )
        log.info("Session '%s' restarted (new pane: %s)", session.id, new_backend_id)

        # Run post_restart hooks
        self._run_lifecycle_hooks("post_restart", session_name=session.name or "", session_id=session.id)

        return True

    # ──────────────────────────────────────────────────────────────
    # Pane I/O
    # ──────────────────────────────────────────────────────────────

    def send_text(self, session_id: str, text: str, press_enter: bool = True) -> bool:
        """Send *text* to the session's tmux pane.

        Returns ``True`` on success, ``False`` if the session or pane is not
        found.
        """
        session = self._resolve_session(session_id)
        if session is None or not session.backend_id:
            log.warning("send_text: session '%s' not found or has no backend pane", session_id)
            return False

        try:
            self.tmux.send_text(session.backend_id, text, press_enter=press_enter)
            return True
        except Exception as exc:
            log.error("send_text failed for session %s: %s", session_id, exc)
            return False

    def capture(self, session_id: str, lines: int = 100) -> str:
        """Capture and return terminal output from the session's tmux pane."""
        session = self._resolve_session(session_id)
        if session is None or not session.backend_id:
            log.warning("capture: session '%s' not found or has no backend pane", session_id)
            return ""

        try:
            return self.tmux.capture(session.backend_id, lines=lines)
        except Exception as exc:
            log.error("capture failed for session %s: %s", session_id, exc)
            return ""

    # ──────────────────────────────────────────────────────────────
    # State updates
    # ──────────────────────────────────────────────────────────────

    def update_last_seen(self, session_id: str) -> None:
        """Update the ``seen_at`` timestamp for a session (last seen / idle since).

        This is called whenever a session is known to be active — e.g. on
        hook events, message delivery, or manual status checks.
        """
        session = self._resolve_session(session_id)
        if session is None:
            return
        now = self._now_ms()
        self.db.execute(
            "UPDATE sessions SET seen_at=?, updated_at=? WHERE id=?",
            (now, now, session.id),
        )

    def get_idle_since(self, session_id: str) -> Optional[int]:
        """Return the epoch-ms timestamp of the session's last activity, or None."""
        session = self._resolve_session(session_id)
        if session is None:
            return None
        return session.seen_at

    def set_hook_state(self, session_id: str, state: str) -> None:
        """Update ``hook_state`` for a session (``'working'``, ``'blocked'``, ``'done'``, ``'idle'``)."""
        valid = {"working", "blocked", "done", "idle"}
        if state not in valid:
            raise ValueError(f"Invalid hook state '{state}'. Must be one of: {valid}")

        session = self._resolve_session(session_id)
        if session is None:
            log.warning("set_hook_state: session '%s' not found", session_id)
            return

        now = self._now_ms()
        self.db.execute(
            """
            UPDATE sessions
               SET hook_state = ?, hook_state_at = ?, status = ?, updated_at = ?
             WHERE id = ?
            """,
            (state, now, state, now, session.id),
        )
        log.debug("Session %s hook_state → %s", session.id, state)

    # ──────────────────────────────────────────────────────────────
    # Git worktree ops
    # ──────────────────────────────────────────────────────────────

    def _create_worktree(self, repo_path: str, branch: str, base_branch: str) -> Path:
        """Create a git worktree for *branch*, branching from *base_branch*.

        The worktree is placed under ``WORKTREES_DIR/<branch-slug>``.
        If *branch* doesn't exist in the repo it is created from *base_branch*.
        Returns the worktree :class:`Path`.
        """
        WORKTREES_DIR.mkdir(parents=True, exist_ok=True)

        # Sanitise branch name for use as directory name.
        slug = branch.replace("/", "-").replace(" ", "_")
        worktree_path = WORKTREES_DIR / slug

        # If the worktree directory already exists, return it as-is.
        if worktree_path.exists():
            log.warning("Worktree path %s already exists; reusing", worktree_path)
            return worktree_path

        # Check whether the branch already exists in the repo.
        check = subprocess.run(
            ["git", "-C", repo_path, "rev-parse", "--verify", branch],
            capture_output=True, text=True,
        )
        branch_exists = check.returncode == 0

        try:
            if branch_exists:
                subprocess.run(
                    ["git", "-C", repo_path, "worktree", "add", str(worktree_path), branch],
                    check=True, capture_output=True, text=True,
                )
            else:
                subprocess.run(
                    [
                        "git", "-C", repo_path,
                        "worktree", "add", "-b", branch,
                        str(worktree_path), base_branch,
                    ],
                    check=True, capture_output=True, text=True,
                )
        except subprocess.CalledProcessError as exc:
            log.error(
                "git worktree add failed: %s\nstdout: %s\nstderr: %s",
                exc.cmd, exc.stdout, exc.stderr,
            )
            raise RuntimeError(f"git worktree add failed: {exc.stderr.strip()}") from exc

        return worktree_path

    def _remove_worktree(self, worktree_path: str) -> None:
        """Remove a git worktree with ``--force``."""
        path = Path(worktree_path)
        if not path.exists():
            log.debug("Worktree path %s does not exist; skipping removal", worktree_path)
            return

        # Determine the repo root (parent of the worktree in the standard layout).
        # We walk up looking for a .git file/dir that isn't the worktree's own.
        repo_path: Optional[str] = None
        for parent in path.parents:
            git_dir = parent / ".git"
            if git_dir.is_dir():
                repo_path = str(parent)
                break

        if repo_path is None:
            log.warning("Cannot determine repo root from worktree path %s", worktree_path)
            return

        try:
            subprocess.run(
                ["git", "-C", repo_path, "worktree", "remove", "--force", worktree_path],
                check=True, capture_output=True, text=True,
            )
            log.debug("Removed git worktree %s", worktree_path)
        except subprocess.CalledProcessError as exc:
            log.error(
                "git worktree remove failed for %s: %s", worktree_path, exc.stderr.strip()
            )
            raise RuntimeError(f"git worktree remove failed: {exc.stderr.strip()}") from exc

    # ──────────────────────────────────────────────────────────────
    # Agent command builder
    # ──────────────────────────────────────────────────────────────

    def _build_agent_command(self, agent: AgentDef, session_id: str, cwd: str) -> str:
        """Build the shell command that starts the agent.

        Substitutions available in ``agent.command``:
        - ``{id}``  → session UUID
        - ``{cwd}`` → working directory path
        - ``{name}`` → agent name

        Falls back to the agent name (bare binary) if no command is configured.
        """
        template = agent.command or agent.name
        cmd = (
            template
            .replace("{id}", session_id)
            .replace("{cwd}", cwd)
            .replace("{name}", agent.name)
        )

        # Prepend any agent-specific env vars as shell assignments.
        if agent.env:
            env_prefix = " ".join(f"{k}={v}" for k, v in agent.env.items())
            cmd = f"{env_prefix} {cmd}"

        return cmd
