"""
Convergence detection — monitors orchestration progress and detects
when further iterations are unlikely to produce improvement.

Ported from kodo's knowledge/convergence.py.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class PatternType(str, Enum):
    """Types of convergence/divergence patterns."""
    CONVERGING = "converging"
    DIVERGING = "diverging"
    STAGNANT = "stagnant"
    OSCILLATING = "oscillating"
    PLATEAU = "plateau"


@dataclass
class ConvergenceState:
    """Tracks convergence state across cycles."""
    round_count: int = 0
    rejection_count: int = 0
    success_count: int = 0
    patterns: list[PatternType] = field(default_factory=list)
    last_rejection_reason: str = ""
    cycle_scores: list[float] = field(default_factory=list)

    def record_round(self, success: bool, score: float = 0.0) -> None:
        """Record a completed cycle round."""
        self.round_count += 1
        if success:
            self.success_count += 1
        else:
            self.rejection_count += 1
        self.cycle_scores.append(score)

    def converged(self) -> bool:
        """Return True if we appear to have converged."""
        if self.round_count < 3:
            return False
        # Converged if last 3 rounds were successful
        if self.success_count >= 3 and self.rejection_count == 0:
            return True
        # Converged if pattern is plateau (no improvement)
        if PatternType.PLATEAU in self.patterns[-2:]:
            return True
        return False

    def diminishing_returns(self) -> bool:
        """Return True if further iterations are unlikely to help."""
        if self.round_count < 5:
            return False
        # Diminishing returns if we've had 3+ rejections in a row
        recent = self.cycle_scores[-5:] if len(self.cycle_scores) >= 5 else self.cycle_scores
        if len(recent) >= 3:
            # Check if scores are not improving
            diffs = [recent[i+1] - recent[i] for i in range(len(recent)-1)]
            if all(d <= 0 for d in diffs):
                return True
        return False

    def verdict_type(self) -> str:
        """Return a human-readable verdict."""
        if self.converged():
            return "converged"
        if self.diminishing_returns():
            return "diminishing_returns"
        if self.rejection_count > self.success_count and self.round_count > 3:
            return "diverging"
        return "in_progress"


def assess_convergence(state: ConvergenceState) -> dict:
    """Assess convergence state and return recommendations."""
    verdict = state.verdict_type()

    recommendations = {
        "converged": "Goal appears achieved. Accept and move to next stage.",
        "diminishing_returns": "Further iterations unlikely to help. Consider accepting with minor issues or changing approach.",
        "diverging": "Work is getting worse. Consider reverting recent changes and trying a different approach.",
        "in_progress": "Continue iterating. Progress is being made.",
    }

    return {
        "verdict": verdict,
        "recommendation": recommendations.get(verdict, "Continue."),
        "rounds": state.round_count,
        "rejections": state.rejection_count,
        "successes": state.success_count,
    }
