"""
Orchestration engine — drives cycles, stages, and verification.

All progress is written to the shared SQLite DB so the TUI can render it live.
This is the unified port of kodo's OrchestratorBase into Synapse's architecture.
"""

from __future__ import annotations

import json
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from typing import Optional

from ..core.config import SynapseConfig
from ..db.database import Database
from ..session.manager import SessionManager
from .git_ops import (
    check_clean_tree,
    create_worktree,
    merge_worktree_branch,
    remove_worktree,
)
from .prompts import EFFORT_SUPPLEMENTS
from .run_log import RunLogger
from .types import (
    CycleResult,
    Effort,
    GoalPlan,
    GoalStage,
    RunMode,
    RunResult,
    RunStatus,
    StageResult,
    StageStatus,
    TeamConfig,
    VerificationResult,
)
from .verification import Verifier


class OrchestrationEngine:
    """Drives the full orchestration lifecycle.

    Responsibilities:
    - Single-stage runs (``_run_single``)
    - Multi-stage sequential / parallel runs (``_run_staged`` / ``_run_parallel_group``)
    - Per-stage cycle loop with rejection feedback (``_run_one_stage``)
    - Independent verification after each successful cycle (``_run_verification``)
    - DB writes so the TUI can render progress live
    - JSONL run logging via :class:`RunLogger`
    """

    def __init__(
        self,
        db: Database,
        session_mgr: SessionManager,
        team: TeamConfig,
        effort: Effort = Effort.standard,
        config: Optional[SynapseConfig] = None,
    ) -> None:
        self.db = db
        self.session_mgr = session_mgr
        self.team = team
        self.effort = effort
        self.config = config or SynapseConfig.load()
        self.verifier = Verifier(team, effort)
        self._run_id: str = ""
        self._logger: RunLogger = RunLogger("__init__")  # replaced in run()

    # ──────────────────────────────────────────────────────────────────────────
    # Main entry point
    # ──────────────────────────────────────────────────────────────────────────

    def run(
        self,
        goal: str,
        repo_path: str,
        plan: Optional[GoalPlan] = None,
        mode: RunMode = RunMode.goal,
        require_clean_tree: bool = True,
    ) -> RunResult:
        """Execute an orchestration run end-to-end.

        Steps:
        1. Optionally enforce a clean git working tree.
        2. Insert a ``runs`` row and stage rows into the DB.
        3. Dispatch to ``_run_staged`` (multi-stage) or ``_run_single``.
        4. Update the run row on completion.
        """
        if require_clean_tree:
            is_clean, status = check_clean_tree(repo_path)
            if not is_clean:
                raise RuntimeError(
                    f"Git tree is not clean. Commit or stash changes before running orchestration.\n{status}"
                )

        self._run_id = str(uuid.uuid4())
        self._logger = RunLogger(self._run_id)  # noqa: F841

        self._insert_run(mode, goal, plan)
        self._logger.run_start(mode.value, goal, self.team.name, self.effort.value)

        try:
            if plan and len(plan.stages) > 1:
                result = self._run_staged(goal, repo_path, plan, mode)
            else:
                result = self._run_single(goal, repo_path, mode)

            final_status = RunStatus.completed if result.success else RunStatus.failed
            self._update_run_status(final_status)
            self._logger.run_end(result.success)
            self._logger.print_stats()
            return result

        except Exception as exc:
            self._update_run_status(RunStatus.failed)
            self._logger.run_end(False, str(exc))
            raise

    # ──────────────────────────────────────────────────────────────────────────
    # Multi-stage orchestration
    # ──────────────────────────────────────────────────────────────────────────

    def _run_staged(
        self,
        goal: str,
        repo_path: str,
        plan: GoalPlan,
        mode: RunMode = RunMode.goal,
    ) -> RunResult:
        """Run all plan stages, grouping parallel stages with ThreadPoolExecutor."""
        run_result = RunResult(run_id=self._run_id, mode=mode)

        # Partition stages into sequential execution units.
        # Stages that share a parallel_group value (non-None) run concurrently;
        # everything else runs one at a time in index order.
        execution_units: list[list[GoalStage]] = []
        seen_groups: dict[int, int] = {}  # parallel_group -> unit index

        for stage in sorted(plan.stages, key=lambda s: s.index):
            if stage.parallel_group is not None:
                grp = stage.parallel_group
                if grp in seen_groups:
                    execution_units[seen_groups[grp]].append(stage)
                else:
                    seen_groups[grp] = len(execution_units)
                    execution_units.append([stage])
            else:
                # Sequential — each gets its own unit
                execution_units.append([stage])

        for unit in execution_units:
            if len(unit) == 1:
                stage_result = self._run_one_stage(
                    unit[0], goal, repo_path, plan.context
                )
                run_result.stage_results.append(stage_result)
                if not stage_result.success:
                    run_result.success = False
                    run_result.error = f"Stage '{unit[0].name}' failed"
                    return run_result
            else:
                parallel_results = self._run_parallel_group(
                    unit, goal, repo_path, plan.context
                )
                run_result.stage_results.extend(parallel_results)
                for sr in parallel_results:
                    if not sr.success:
                        run_result.success = False
                        run_result.error = f"Stage '{sr.stage.name}' failed"
                        return run_result

        run_result.success = all(sr.success for sr in run_result.stage_results)
        return run_result

    def _run_parallel_group(
        self,
        stages: list[GoalStage],
        goal: str,
        repo_path: str,
        plan_context: str = "",
    ) -> list[StageResult]:
        """Run a group of stages concurrently using git worktrees."""
        max_parallel = self.config.max_parallel if self.config else 2
        results: list[StageResult] = []

        with ThreadPoolExecutor(max_workers=min(len(stages), max_parallel)) as executor:
            futures: dict[Future[StageResult], tuple[GoalStage, str, str]] = {}
            for stage in stages:
                wt_path, branch = create_worktree(repo_path, self._run_id, stage.index)
                future = executor.submit(
                    self._run_one_stage,
                    stage,
                    goal,
                    str(wt_path),
                    plan_context,
                )
                futures[future] = (stage, str(wt_path), branch)

            for future in as_completed(futures):
                stage, wt_path, branch = futures[future]
                stage_result: StageResult
                try:
                    stage_result = future.result()
                    if stage_result.success and stage.persist_changes:
                        merge_ok, conflicts = merge_worktree_branch(repo_path, branch)
                        if not merge_ok and conflicts:
                            # Log conflicts for potential agent-assisted resolution
                            from .git_ops import build_conflict_resolution_prompt
                            prompt = build_conflict_resolution_prompt(conflicts, branch)
                            log.warning(
                                "Merge conflicts in %s: %s",
                                branch, conflicts,
                            )
                except Exception as exc:
                    stage_result = StageResult(
                        stage=stage, success=False, error=str(exc)
                    )
                finally:
                    _ = remove_worktree(repo_path, wt_path, branch)

                results.append(stage_result)

        return results

    # ──────────────────────────────────────────────────────────────────────────
    # Single-stage / single-goal shortcut
    # ──────────────────────────────────────────────────────────────────────────

    def _run_single(
        self,
        goal: str,
        repo_path: str,
        mode: RunMode = RunMode.goal,
    ) -> RunResult:
        """Convenience wrapper for a goal with no explicit multi-stage plan."""
        stage = GoalStage(index=1, name="Main", description=goal)
        stage_result = self._run_one_stage(stage, goal, repo_path)
        return RunResult(
            run_id=self._run_id,
            mode=mode,
            stage_results=[stage_result],
            success=stage_result.success,
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Stage cycle loop
    # ──────────────────────────────────────────────────────────────────────────

    def _run_one_stage(
        self,
        stage: GoalStage,
        overall_goal: str,
        cwd: str,
        plan_context: str = "",
    ) -> StageResult:
        """Run one stage through the cycle loop.

        Each cycle: build prompt → call worker agent → check done signal →
        (if done) run verification → accept or feed rejection back as context
        for the next cycle.
        """
        stage_goal = stage.description
        if stage.acceptance_criteria:
            stage_goal += f"\n\nAcceptance criteria:\n{stage.acceptance_criteria}"

        self._update_stage_status(stage.index, StageStatus.running)
        self._logger.stage_start(stage.index, stage.name)

        cycle_index = 0
        prior_summary = ""
        cycles: list[CycleResult] = []
        max_cycles = 20

        while cycle_index < max_cycles:
            self._logger.cycle_start(cycle_index, stage.index)

            cycle_result = self._run_cycle(
                stage_goal, cwd, cycle_index, prior_summary, stage
            )
            cycles.append(cycle_result)
            self._insert_cycle(stage.index, cycle_result)
            self._logger.cycle_end(cycle_index, cycle_result)

            if cycle_result.finished:
                if cycle_result.success:
                    # Independent verification pass
                    if stage.verification == "full" and self.team.verifiers:
                        ver = self._run_verification(stage_goal, cwd)
                        self._logger.verification_result(ver.passed, ver.rejection_reason)

                        if ver.passed:
                            self._update_stage_status(stage.index, StageStatus.completed)
                            self._logger.stage_end(stage.index, True)
                            return StageResult(stage=stage, cycles=cycles, success=True)
                        else:
                            # Feed rejection back into the next cycle
                            prior_summary = (
                                f"Previous attempt was REJECTED by verification:\n"
                                f"{ver.rejection_reason}\n\n"
                                f"Fix these issues and try again."
                            )
                            cycle_index += 1
                            continue
                    else:
                        # No verification configured — accept the cycle result
                        self._update_stage_status(stage.index, StageStatus.completed)
                        self._logger.stage_end(stage.index, True)
                        return StageResult(stage=stage, cycles=cycles, success=True)
                else:
                    prior_summary = cycle_result.summary
            else:
                prior_summary = cycle_result.summary

            cycle_index += 1

        # Exhausted max cycles
        self._update_stage_status(stage.index, StageStatus.failed)
        self._logger.stage_end(stage.index, False)
        return StageResult(
            stage=stage,
            cycles=cycles,
            success=False,
            error="Max cycles reached without success",
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Single cycle
    # ──────────────────────────────────────────────────────────────────────────

    def _run_cycle(
        self,
        goal: str,
        cwd: str,
        cycle_index: int,
        prior_summary: str,
        stage: GoalStage,
    ) -> CycleResult:
        """Execute one orchestrator cycle.

        In the baseline implementation the orchestrator simply forwards the
        goal to the ``worker_smart`` agent.  The full LLM-driven multi-tool
        orchestrator (which calls ask_worker_fast, ask_architect, etc.) is
        wired in ``orchestrator/api_orchestrator.py``.
        """
        prompt = self._build_cycle_prompt(goal, cwd, prior_summary)

        worker_output = self._call_agent("worker_smart", prompt, cwd)

        # Treat any non-error output as a completed, successful cycle.
        finished = True
        success = not worker_output.startswith("[Agent error:")
        summary = worker_output[:500] if worker_output else ""

        return CycleResult(
            cycle_index=cycle_index,
            exchanges=1,
            summary=summary,
            finished=finished,
            success=success,
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Verification
    # ──────────────────────────────────────────────────────────────────────────

    def _run_verification(self, goal: str, cwd: str) -> VerificationResult:
        """Run independent verification using the configured verifier roles."""
        def session_runner(role: str, prompt: str, _cwd: str) -> str:
            return self._call_agent(role, prompt, _cwd)

        return self.verifier.verify(goal, cwd, session_runner)

    # ──────────────────────────────────────────────────────────────────────────
    # Agent invocation
    # ──────────────────────────────────────────────────────────────────────────

    def _call_agent(self, role: str, prompt: str, cwd: str) -> str:
        """Call an agent by role name.

        Creates (or reuses) a tmux session for the role, sends the prompt, then
        polls the DB until ``hook_state == 'done'`` or the agent times out.
        """
        agent_cfg = self.team.agents.get(role)
        if not agent_cfg:
            return f"[No {role} agent configured in team '{self.team.name}']"

        self._logger.agent_call(role, prompt[:200])

        session_name = f"synapse-{self._run_id[:8]}-{role}"
        try:
            session = self.session_mgr.create_session(
                name=session_name,
                repo_path=cwd,
                agent=agent_cfg.backend,
                tag="synapse-run",
            )
            self.session_mgr.send_text(session.id, prompt)

            output = self._wait_for_agent(session.id, timeout=agent_cfg.timeout_s)
            self._logger.agent_result(role, output[:200])
            return output

        except Exception as exc:
            err = f"[Agent error: {exc}]"
            self._logger.agent_result(role, err)
            return err

    def _wait_for_agent(self, session_id: str, timeout: int = 1800) -> str:
        """Poll the DB until ``hook_state == 'done'`` or *timeout* seconds elapse.

        Returns the captured terminal output.
        """
        deadline = time.time() + timeout
        poll_interval = 5  # seconds between DB polls

        while time.time() < deadline:
            session = self.session_mgr.get_session(session_id)
            if session and session.hook_state == "done":
                return self.session_mgr.capture(session_id, lines=200)
            time.sleep(poll_interval)

        return "[Timeout waiting for agent to complete]"

    # ──────────────────────────────────────────────────────────────────────────
    # Prompt construction
    # ──────────────────────────────────────────────────────────────────────────

    def _build_cycle_prompt(
        self,
        goal: str,
        cwd: str,
        prior_summary: str,
    ) -> str:
        effort_supp = EFFORT_SUPPLEMENTS.get(self.effort.value, "")
        parts: list[str] = [
            f"# Goal\n{goal}",
            f"Project directory: {cwd}",
        ]
        if prior_summary:
            parts.append(f"# Previous progress / context\n{prior_summary}")
        if effort_supp:
            parts.append(f"# Effort guidance\n{effort_supp}")
        return "\n\n".join(parts)

    # ──────────────────────────────────────────────────────────────────────────
    # DB helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _insert_run(self, mode: RunMode, goal: str, plan: Optional[GoalPlan]) -> None:
        now = self.db.now_ms()
        plan_json: Optional[str] = None

        if plan:
            plan_json = json.dumps({
                "context": plan.context,
                "stages": [
                    {
                        "index": s.index,
                        "name": s.name,
                        "description": s.description,
                        "acceptance_criteria": s.acceptance_criteria,
                        "parallel_group": s.parallel_group,
                        "persist_changes": s.persist_changes,
                        "verification": s.verification,
                    }
                    for s in plan.stages
                ],
            })
            # Insert a row for every stage so the TUI can show them immediately
            for s in plan.stages:
                self.db.execute(
                    """INSERT INTO stages
                       (run_id, stage_index, name, description,
                        acceptance_criteria, parallel_group, status, verification)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (
                        self._run_id, s.index, s.name, s.description,
                        s.acceptance_criteria, s.parallel_group,
                        StageStatus.pending.value, s.verification,
                    ),
                )

        self.db.execute(
            """INSERT INTO runs
               (id, mode, goal, status, effort, team_name, plan_json, created_at, started_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                self._run_id, mode.value, goal,
                RunStatus.running.value, self.effort.value,
                self.team.name, plan_json, now, now,
            ),
        )

    def _insert_cycle(self, stage_index: int, result: CycleResult) -> None:
        now = self.db.now_ms()
        stage_row = self.db.fetchone(
            "SELECT id FROM stages WHERE run_id=? AND stage_index=?",
            (self._run_id, stage_index),
        )
        stage_id = stage_row["id"] if stage_row else None

        self.db.execute(
            """INSERT INTO cycles
               (run_id, stage_id, cycle_index, exchanges,
                api_cost_usd, virtual_cost_usd, summary,
                finished, success, started_at, completed_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                self._run_id, stage_id, result.cycle_index, result.exchanges,
                result.api_cost_usd, result.virtual_cost_usd, result.summary,
                1 if result.finished else 0,
                1 if result.success else 0,
                now, now,
            ),
        )

    def _update_stage_status(self, stage_index: int, status: StageStatus) -> None:
        now = self.db.now_ms()
        terminal = status in (StageStatus.completed, StageStatus.failed)

        if terminal:
            self.db.execute(
                "UPDATE stages SET status=?, completed_at=? WHERE run_id=? AND stage_index=?",
                (status.value, now, self._run_id, stage_index),
            )
        else:
            self.db.execute(
                "UPDATE stages SET status=? WHERE run_id=? AND stage_index=?",
                (status.value, self._run_id, stage_index),
            )

    def _update_run_status(self, status: RunStatus) -> None:
        now = self.db.now_ms()
        self.db.execute(
            "UPDATE runs SET status=?, completed_at=? WHERE id=?",
            (status.value, now, self._run_id),
        )
