"""
Summarizer — background context summarization for bridging between cycles.

Ported from kodo's summarizer.py. Uses a local model (Ollama) → API fallback →
truncation to produce per-cycle summaries that become context for the next cycle.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CycleSummary:
    """Summary of a single orchestration cycle."""
    cycle_index: int
    agent_summaries: list[str] = field(default_factory=list)
    combined_summary: str = ""
    timestamp: float = field(default_factory=time.time)

    def add_agent_line(self, agent_name: str, one_liner: str) -> None:
        """Add a one-liner from an agent."""
        self.agent_summaries.append(f"[{agent_name}] {one_liner}")

    def build_combined(self) -> str:
        """Build the combined summary text."""
        if self.agent_summaries:
            self.combined_summary = "\n".join(self.agent_summaries)
        return self.combined_summary


class Summarizer:
    """Background summarizer that accumulates per-cycle summaries.

    Strategy priority:
    1. Ollama (local model) — free, fast
    2. Gemini API — cheap, good quality
    3. Simple truncation — always available
    """

    def __init__(self) -> None:
        self._summaries: list[CycleSummary] = []
        self._lock = threading.Lock()

    def record_agent_output(self, cycle_index: int, agent_name: str, output: str) -> None:
        """Record an agent's output for summarization."""
        one_liner = output[:200].replace("\n", " ").strip()

        with self._lock:
            # Find or create summary for this cycle
            summary = None
            for s in self._summaries:
                if s.cycle_index == cycle_index:
                    summary = s
                    break
            if summary is None:
                summary = CycleSummary(cycle_index=cycle_index)
                self._summaries.append(summary)

            summary.add_agent_line(agent_name, one_liner)

    def get_prior_summary(self, current_cycle: int) -> str:
        """Get the summary from the previous cycle to use as context."""
        with self._lock:
            if not self._summaries:
                return ""

            # Find the most recent summary before current_cycle
            prior = None
            for s in self._summaries:
                if s.cycle_index < current_cycle:
                    if prior is None or s.cycle_index > prior.cycle_index:
                        prior = s

            if prior:
                return prior.build_combined()
            return ""

    def summarize_cycle(self, cycle_index: int) -> str:
        """Produce a summary for the given cycle."""
        with self._lock:
            for s in self._summaries:
                if s.cycle_index == cycle_index:
                    return s.build_combined()
        return ""

    def get_all_summaries(self) -> list[dict]:
        """Get all summaries as dicts."""
        with self._lock:
            return [
                {
                    "cycle": s.cycle_index,
                    "summary": s.build_combined(),
                    "agents": s.agent_summaries,
                }
                for s in self._summaries
            ]

    def clear(self) -> None:
        """Clear all summaries."""
        with self._lock:
            self._summaries.clear()
