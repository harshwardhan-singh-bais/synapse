"""Data types for the Synapse orchestration system."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Effort(str, Enum):
    low = "low"
    standard = "standard"
    high = "high"
    max = "max"


class RunMode(str, Enum):
    goal = "goal"
    test = "test"
    improve = "improve"
    fix_from = "fix-from"
    resume = "resume"


class StageStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class RunStatus(str, Enum):
    running = "running"
    completed = "completed"
    failed = "failed"
    paused = "paused"


@dataclass
class AgentConfig:
    """Configuration for one role's agent."""

    role: str           # 'worker_smart' | 'worker_fast' | 'architect' | 'tester' | 'tester_browser'
    backend: str        # 'claude' | 'cursor' | 'codex' | 'gemini-cli'
    model: str
    description: str
    system_prompt: str = ""
    max_turns: int = 30
    timeout_s: int = 1800
    session_timeout_s: int = 7200


@dataclass
class TeamConfig:
    """Full team definition."""

    name: str
    agents: dict[str, AgentConfig]  # role -> AgentConfig
    verifiers: dict[str, list[str]] = field(default_factory=lambda: {
        "testers": ["tester"],
        "reviewers": ["architect"],
    })
    orchestrator_prompt: str = ""


@dataclass
class GoalStage:
    index: int
    name: str
    description: str
    acceptance_criteria: str = ""
    parallel_group: Optional[int] = None
    persist_changes: bool = True
    verification: str = "full"  # 'full' | 'skip'


@dataclass
class GoalPlan:
    stages: list[GoalStage]
    context: str = ""


@dataclass
class CycleResult:
    cycle_index: int
    exchanges: int = 0
    api_cost_usd: float = 0.0
    virtual_cost_usd: float = 0.0
    summary: str = ""
    finished: bool = False
    success: bool = False


@dataclass
class StageResult:
    stage: GoalStage
    cycles: list[CycleResult] = field(default_factory=list)
    success: bool = False
    error: Optional[str] = None


@dataclass
class RunResult:
    run_id: str
    mode: RunMode
    stage_results: list[StageResult] = field(default_factory=list)
    success: bool = False
    error: Optional[str] = None


@dataclass
class DoneSignal:
    """Shared mutable state passed between tool handlers and the cycle loop."""

    called: bool = False
    terminal: str = "end_cycle"   # 'goal_done' | 'end_cycle' | 'raise_issue'
    summary: str = ""
    success: bool = False


@dataclass
class VerificationResult:
    passed: bool
    tester_report: str = ""
    architect_report: str = ""
    rejection_reason: str = ""
