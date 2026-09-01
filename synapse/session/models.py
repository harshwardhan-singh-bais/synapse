"""Pydantic v2 models mirroring the Synapse SQLite schema."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict


# ──────────────────────────────────────────────────────────────────────────────
# Enums
# ──────────────────────────────────────────────────────────────────────────────


class SessionStatus(str, Enum):
    """Lifecycle state of an agent session."""

    idle = "idle"
    working = "working"
    blocked = "blocked"
    done = "done"
    error = "error"
    unreachable = "unreachable"


# ──────────────────────────────────────────────────────────────────────────────
# Base
# ──────────────────────────────────────────────────────────────────────────────


class _Base(BaseModel):
    """Shared config for all Synapse models.

    ``from_attributes=True`` allows constructing from ORM rows or
    ``sqlite3.Row`` objects via ``model_validate``.
    """

    model_config = ConfigDict(from_attributes=True)


# ──────────────────────────────────────────────────────────────────────────────
# Session & related
# ──────────────────────────────────────────────────────────────────────────────


class SessionInfo(_Base):
    """Mirror of the ``sessions`` table."""

    id: str                               # UUID
    name: str
    agent: Optional[str] = None           # agent name from agents.toml
    backend_id: Optional[str] = None      # tmux pane id
    backend_type: Optional[str] = None    # 'local-tmux' | 'ssh:<name>' | 'wsl:<name>'
    agent_session_id: Optional[str] = None
    cwd: Optional[str] = None
    hook_state: Optional[str] = None      # 'working' | 'blocked' | 'done' | 'idle'
    hook_state_at: Optional[int] = None   # epoch ms
    seen_at: Optional[int] = None
    tag: Optional[str] = None             # group label (from hcom)
    status: Optional[str] = None          # 'active' | 'idle' | 'working' | 'blocked' | 'done' | 'error'
    pid: Optional[int] = None
    hints: Optional[str] = None
    display_order: Optional[int] = None
    parent_session_id: Optional[str] = None
    created_at: Optional[int] = None
    updated_at: Optional[int] = None
    deleted_at: Optional[int] = None


class WorktreeInfo(_Base):
    """Mirror of the ``worktrees`` table."""

    id: int
    session_id: Optional[str] = None
    repo_path: Optional[str] = None
    worktree_path: Optional[str] = None
    branch: Optional[str] = None
    created_at: Optional[int] = None
    deleted_at: Optional[int] = None


# ──────────────────────────────────────────────────────────────────────────────
# Messaging
# ──────────────────────────────────────────────────────────────────────────────


class MessageRecord(_Base):
    """Mirror of the ``messages`` table."""

    id: int
    to_session_id: Optional[str] = None    # NULL = broadcast
    from_session_id: Optional[str] = None
    kind: Optional[str] = None             # 'chat' | 'questions' | 'plan' | 'result' | 'status' | 'collision'
    body: Optional[str] = None
    thread_id: Optional[str] = None
    intent: Optional[str] = None           # 'request' | 'inform' | 'ack'
    claimed_at: Optional[int] = None       # NULL = unclaimed
    wake_flag: int = 0
    created_at: Optional[int] = None


# ──────────────────────────────────────────────────────────────────────────────
# Automations & tasks
# ──────────────────────────────────────────────────────────────────────────────


class AutomationRecord(_Base):
    """Mirror of the ``automations`` table."""

    id: str                                     # UUID
    name: Optional[str] = None
    enabled: int = 1
    schedule_kind: Optional[str] = None         # 'once' | 'cron'
    schedule_spec: Optional[str] = None
    timezone: Optional[str] = None
    action_kind: Optional[str] = None           # 'send' | 'spawn' | 'exec'
    action_target_session: Optional[str] = None
    action_repo_path: Optional[str] = None
    action_worktree_branch: Optional[str] = None
    action_base_branch: Optional[str] = None
    action_agent: Optional[str] = None
    action_command: Optional[str] = None
    prompt: Optional[str] = None
    next_run_at: Optional[int] = None
    last_run_at: Optional[int] = None
    created_at: Optional[int] = None
    updated_at: Optional[int] = None


class TaskRecord(_Base):
    """Mirror of the ``tasks`` table."""

    id: int
    title: Optional[str] = None
    description: Optional[str] = None
    status: str = "todo"                        # 'todo' | 'in_progress' | 'done'
    action_kind: Optional[str] = None
    action_target_session: Optional[str] = None
    action_repo_path: Optional[str] = None
    action_worktree_branch: Optional[str] = None
    action_base_branch: Optional[str] = None
    action_agent: Optional[str] = None
    action_command: Optional[str] = None
    source: str = "local"
    external_id: Optional[str] = None
    external_url: Optional[str] = None
    created_at: Optional[int] = None
    updated_at: Optional[int] = None
    deleted_at: Optional[int] = None


# ──────────────────────────────────────────────────────────────────────────────
# Orchestration (kodo)
# ──────────────────────────────────────────────────────────────────────────────


class RunRecord(_Base):
    """Mirror of the ``runs`` table."""

    id: str                                     # UUID
    mode: Optional[str] = None                  # 'goal' | 'test' | 'improve' | 'fix-from' | 'resume'
    goal: Optional[str] = None
    status: Optional[str] = None                # 'running' | 'completed' | 'failed' | 'paused'
    effort: Optional[str] = None                # 'low' | 'standard' | 'high' | 'max'
    team_name: Optional[str] = None
    team_json: Optional[str] = None             # full team config JSON
    plan_json: Optional[str] = None             # GoalPlan JSON
    started_at: Optional[int] = None
    completed_at: Optional[int] = None
    created_at: Optional[int] = None


class StageRecord(_Base):
    """Mirror of the ``stages`` table."""

    id: int
    run_id: Optional[str] = None
    stage_index: Optional[int] = None
    name: Optional[str] = None
    description: Optional[str] = None
    acceptance_criteria: Optional[str] = None
    parallel_group: Optional[int] = None
    status: Optional[str] = None                # 'pending' | 'running' | 'completed' | 'failed'
    verification: Optional[str] = None          # 'full' | 'skip'
    started_at: Optional[int] = None
    completed_at: Optional[int] = None


class CycleRecord(_Base):
    """Mirror of the ``cycles`` table."""

    id: int
    run_id: Optional[str] = None
    stage_id: Optional[int] = None
    cycle_index: Optional[int] = None
    exchanges: Optional[int] = None
    api_cost_usd: Optional[float] = None
    virtual_cost_usd: Optional[float] = None
    summary: Optional[str] = None
    finished: int = 0
    success: int = 0
    started_at: Optional[int] = None
    completed_at: Optional[int] = None


# ──────────────────────────────────────────────────────────────────────────────
# Goal planning — canonical definitions live in orchestrator.types;
# re-export here for backward compatibility.
# ──────────────────────────────────────────────────────────────────────────────

from ..orchestrator.types import GoalPlan, GoalStage  # noqa: F401, E402
