"""
Run logging — JSONL event emission to ~/.local/share/synapse/runs/{run_id}/log.jsonl

One log file per run.  Each line is a self-contained JSON object with at least
``ts`` (epoch seconds), ``event`` (string type tag), and ``data`` (payload).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from ..core.paths import RUNS_DIR

# Forward reference — CycleResult is defined in .types but we avoid a
# circular import by using a string annotation here.
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .types import CycleResult


# ──────────────────────────────────────────────────────────────────────────────
# Stats accumulator
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class RunStats:
    api_cost_usd: float = 0.0
    virtual_cost_usd: float = 0.0
    exchanges: int = 0
    cycles: int = 0

    def add(self, bucket: str, amount: float) -> None:
        if bucket == "api":
            self.api_cost_usd += amount
        else:
            self.virtual_cost_usd += amount


# ──────────────────────────────────────────────────────────────────────────────
# Logger
# ──────────────────────────────────────────────────────────────────────────────


class RunLogger:
    """Append-only JSONL logger for a single orchestration run.

    Each ``emit`` call appends one line to the log file.  All other methods
    are named event helpers that call ``emit`` with a structured payload.
    """

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.run_dir: Path = RUNS_DIR / run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.log_path: Path = self.run_dir / "log.jsonl"
        self.stats = RunStats()

    # ──────────────────────────────────────────────────────────────
    # Core emitter
    # ──────────────────────────────────────────────────────────────

    def emit(self, event_type: str, data: dict[str, object]) -> None:
        """Append a JSONL event to the log file."""
        record = {
            "ts": time.time(),
            "event": event_type,
            "run_id": self.run_id,
            **data,
        }
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")

    # ──────────────────────────────────────────────────────────────
    # Named event helpers
    # ──────────────────────────────────────────────────────────────

    def run_start(self, mode: str, goal: str, team: str, effort: str) -> None:
        self.emit("run_start", {
            "mode": mode,
            "goal": goal[:500],
            "team": team,
            "effort": effort,
        })

    def run_end(self, success: bool, error: str = "") -> None:
        self.emit("run_end", {
            "success": success,
            "error": error[:500] if error else "",
            "api_cost_usd": round(self.stats.api_cost_usd, 6),
            "virtual_cost_usd": round(self.stats.virtual_cost_usd, 6),
            "total_exchanges": self.stats.exchanges,
            "total_cycles": self.stats.cycles,
        })

    def stage_start(self, stage_index: int, stage_name: str) -> None:
        self.emit("stage_start", {
            "stage_index": stage_index,
            "stage_name": stage_name,
        })

    def stage_end(self, stage_index: int, success: bool) -> None:
        self.emit("stage_end", {
            "stage_index": stage_index,
            "success": success,
        })

    def cycle_start(self, cycle_index: int, stage_index: int) -> None:
        self.stats.cycles += 1
        self.emit("cycle_start", {
            "cycle_index": cycle_index,
            "stage_index": stage_index,
        })

    def cycle_end(self, cycle_index: int, result: "CycleResult") -> None:
        self.stats.exchanges += result.exchanges
        self.stats.api_cost_usd += result.api_cost_usd
        self.stats.virtual_cost_usd += result.virtual_cost_usd
        self.emit("cycle_end", {
            "cycle_index": cycle_index,
            "exchanges": result.exchanges,
            "api_cost_usd": result.api_cost_usd,
            "virtual_cost_usd": result.virtual_cost_usd,
            "finished": result.finished,
            "success": result.success,
            "summary": result.summary[:300] if result.summary else "",
        })

    def agent_call(self, role: str, prompt_preview: str) -> None:
        self.emit("agent_call", {
            "role": role,
            "prompt_preview": prompt_preview[:200],
        })

    def agent_result(
        self,
        role: str,
        result_preview: str,
        cost_usd: float = 0.0,
    ) -> None:
        self.emit("agent_result", {
            "role": role,
            "result_preview": result_preview[:200],
            "cost_usd": cost_usd,
        })

    def verification_result(self, passed: bool, rejection_reason: str = "") -> None:
        self.emit("verification_result", {
            "passed": passed,
            "rejection_reason": rejection_reason[:500] if rejection_reason else "",
        })

    # ──────────────────────────────────────────────────────────────
    # Summary
    # ──────────────────────────────────────────────────────────────

    def print_stats(self) -> None:
        """Print a cost/exchange summary table to stdout."""
        sep = "-" * 44
        print(sep)
        print(f"  {'Run':20s}  {self.run_id[:8]}")
        print(f"  {'API cost':20s}  ${self.stats.api_cost_usd:>9.4f}")
        print(f"  {'Virtual cost':20s}  ${self.stats.virtual_cost_usd:>9.4f}")
        print(f"  {'Total cost':20s}  ${(self.stats.api_cost_usd + self.stats.virtual_cost_usd):>9.4f}")
        print(f"  {'Exchanges':20s}  {self.stats.exchanges:>10d}")
        print(f"  {'Cycles':20s}  {self.stats.cycles:>10d}")
        print(sep)
