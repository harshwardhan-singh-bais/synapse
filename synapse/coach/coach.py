"""
Coach — monitors orchestration dispatches, detects drift/circles/over-decomposition,
and pushes advisories to the orchestrator.

Ported from kodo's coach.py and advisory.py.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Advisory:
    """A single advisory message from the coach."""
    id: str
    message: str
    severity: str = "info"  # 'info' | 'warning' | 'critical'
    timestamp: float = field(default_factory=time.time)
    dismissed: bool = False


class AdvisoryQueue:
    """Thread-safe queue for coach advisories."""

    def __init__(self) -> None:
        self._advisories: list[Advisory] = []
        self._lock = threading.Lock()
        self._counter = 0

    def push(self, message: str, severity: str = "info") -> Advisory:
        """Push a new advisory."""
        with self._lock:
            self._counter += 1
            advisory = Advisory(
                id=f"adv-{self._counter}",
                message=message,
                severity=severity,
            )
            self._advisories.append(advisory)
            return advisory

    def pop_undelivered(self) -> list[Advisory]:
        """Get all undismissed advisories."""
        with self._lock:
            return [a for a in self._advisories if not a.dismissed]

    def dismiss(self, advisory_id: str) -> bool:
        """Dismiss an advisory by ID."""
        with self._lock:
            for a in self._advisories:
                if a.id == advisory_id:
                    a.dismissed = True
                    return True
            return False

    def format_for_prompt(self) -> str:
        """Format undismissed advisories for inclusion in the cycle prompt."""
        advisories = self.pop_undelivered()
        if not advisories:
            return ""

        lines = ["# Coach Advisories", ""]
        for a in advisories:
            icon = {"info": "ℹ", "warning": "⚠", "critical": "🚨"}.get(a.severity, "?")
            lines.append(f"- {icon} [{a.severity}] {a.message}")
        return "\n".join(lines)


@dataclass
class DispatchRecord:
    """Record of a single agent dispatch."""
    role: str
    prompt_preview: str
    timestamp: float = field(default_factory=time.time)
    result: Optional[str] = None
    success: Optional[bool] = None


class Coach:
    """Monitors orchestration and detects problems.

    The coach runs as a background thread and periodically assesses
    whether the orchestrator is making progress or getting stuck.
    """

    def __init__(self, advisory_queue: Optional[AdvisoryQueue] = None) -> None:
        self.advisories = advisory_queue or AdvisoryQueue()
        self._dispatches: list[DispatchRecord] = []
        self._lock = threading.Lock()

    def record_dispatch(self, role: str, prompt: str) -> None:
        """Record that an agent was dispatched."""
        with self._lock:
            self._dispatches.append(DispatchRecord(
                role=role,
                prompt_preview=prompt[:200],
            ))

    def record_result(self, role: str, result: str, success: bool) -> None:
        """Record the result of a dispatch."""
        with self._lock:
            for d in reversed(self._dispatches):
                if d.role == role and d.result is None:
                    d.result = result[:200]
                    d.success = success
                    break

    def assess(self) -> None:
        """Assess the current state and push advisories if needed."""
        with self._lock:
            recent = self._dispatches[-20:] if len(self._dispatches) > 20 else self._dispatches

        if len(recent) < 3:
            return

        # Check for repeated failures
        failures = [d for d in recent if d.success is False]
        if len(failures) >= 3:
            self.advisories.push(
                f"Multiple recent failures ({len(failures)} in last {len(recent)} dispatches). "
                "Consider changing approach or simplifying the task.",
                severity="warning",
            )

        # Check for same role dispatched repeatedly without results
        role_counts: dict[str, int] = {}
        for d in recent:
            if d.result is None:
                role_counts[d.role] = role_counts.get(d.role, 0) + 1
        for role, count in role_counts.items():
            if count >= 3:
                self.advisories.push(
                    f"Agent '{role}' has been dispatched {count} times without results. "
                    "Check if the agent is stuck or the task is too complex.",
                    severity="warning",
                )

        # Check for over-decomposition
        unique_prompts = set(d.prompt_preview[:50] for d in recent)
        if len(unique_prompts) < len(recent) * 0.3 and len(recent) >= 5:
            self.advisories.push(
                "Many dispatches have similar prompts. The orchestrator may be "
                "over-decomposing the task or repeating the same approach.",
                severity="info",
            )

    def get_advisories_for_prompt(self) -> str:
        """Get formatted advisories for inclusion in the cycle prompt."""
        return self.advisories.format_for_prompt()

    def clear(self) -> None:
        """Clear all dispatch history."""
        with self._lock:
            self._dispatches.clear()
