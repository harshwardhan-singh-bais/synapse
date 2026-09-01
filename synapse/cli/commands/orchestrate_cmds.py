"""Click commands for `synapse orchestrate`."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import click

import os

from ...backend.tmux import TmuxBackend
from ...core.config import SynapseConfig
from ...db.database import Database
from ...orchestrator.engine import OrchestrationEngine
from ...orchestrator.team_factory import load_team
from ...orchestrator.types import Effort, GoalPlan, GoalStage, RunMode
from ...session.manager import SessionManager


# ──────────────────────────────────────────────────────────────────────────────
# Shared factory
# ──────────────────────────────────────────────────────────────────────────────


def _make_engine(ctx: click.Context, team_name: str, effort_str: str) -> OrchestrationEngine:
    """Create the best available orchestration engine.

    Uses the LLM-driven ApiOrchestrator when an API key is available
    (GOOGLE_API_KEY, ANTHROPIC_API_KEY, or OPENAI_API_KEY).  Falls back
    to the base OrchestrationEngine (direct tmux dispatch) otherwise.
    """
    config: SynapseConfig = ctx.obj["config"]
    db = Database(config.db_path)
    tmux = TmuxBackend()
    session_mgr = SessionManager(db, tmux, config)
    team = load_team(team_name)
    effort = Effort(effort_str)

    # Check if an API key is available for LLM orchestration
    has_api_key = any(
        os.environ.get(key)
        for key in ("GOOGLE_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY")
    )

    if has_api_key:
        try:
            from ...orchestrator.api_orchestrator import ApiOrchestrator
            click.echo(
                click.style("  ℹ", fg="blue")
                + " API key detected — using LLM-driven orchestration"
            )
            return ApiOrchestrator(db, session_mgr, team, effort, config)
        except ImportError as exc:
            click.echo(
                click.style(f"  ⚠ pydantic-ai not available ({exc}), using direct dispatch", fg="yellow")
            )

    return OrchestrationEngine(db, session_mgr, team, effort, config)


def _resolve_goal(goal: Optional[str], goal_file: Optional[str]) -> str:
    """Return goal text from the argument or a file, prompting interactively if neither given."""
    if goal_file:
        return Path(goal_file).read_text(encoding="utf-8").strip()
    if goal:
        return goal
    # Interactive fallback
    lines: list[str] = []
    click.echo("Enter goal (blank line to finish):")
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line == "":
            break
        lines.append(line)
    if not lines:
        click.echo(click.style("No goal provided — aborting.", fg="red"), err=True)
        sys.exit(1)
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# Commands
# ──────────────────────────────────────────────────────────────────────────────


@click.command("goal")
@click.argument("goal", required=False)
@click.option("--goal-file", type=click.Path(exists=True), default=None,
              help="Read goal from a file instead of the command line.")
@click.option("--repo-path", required=True, type=click.Path(exists=True),
              help="Path to the git repository to operate on.")
@click.option("--effort", type=click.Choice(["low", "standard", "high", "max"]),
              default="standard", show_default=True,
              help="Effort level — controls how hard agents push for quality.")
@click.option("--team", default="full", show_default=True,
              help="Team preset or name: full | quick | test, or a custom team name.")
@click.option("--skip-intake", is_flag=True,
              help="Skip the interactive goal-refinement step (not yet implemented).")
@click.option("--allow-dirty", is_flag=True,
              help="Skip the clean git tree check (use with caution).")
@click.pass_context
def orchestrate_goal(
    ctx: click.Context,
    goal: Optional[str],
    goal_file: Optional[str],
    repo_path: str,
    effort: str,
    team: str,
    skip_intake: bool,
    allow_dirty: bool,
) -> None:
    """Run autonomous goal-driven orchestration.

    GOAL is the high-level description of what the agent team should accomplish.
    If omitted, you will be prompted to enter it interactively.
    """
    goal_text = _resolve_goal(goal, goal_file)

    click.echo(
        click.style("synapse orchestrate goal", fg="cyan", bold=True)
        + f"  team={team}  effort={effort}"
    )
    click.echo(f"  goal: {goal_text[:120]}{'...' if len(goal_text) > 120 else ''}")
    click.echo(f"  repo: {repo_path}")

    engine = _make_engine(ctx, team, effort)
    try:
        result = engine.run(
            goal=goal_text,
            repo_path=repo_path,
            mode=RunMode.goal,
            require_clean_tree=not allow_dirty,
        )
    except RuntimeError as exc:
        click.echo(click.style(f"Error: {exc}", fg="red"), err=True)
        sys.exit(1)

    if result.success:
        click.echo(click.style("  Run completed successfully.", fg="green", bold=True))
    else:
        click.echo(
            click.style(
                f"  Run failed: {result.error or 'unknown error'}",
                fg="red",
                bold=True,
            ),
            err=True,
        )
        sys.exit(1)


@click.command("test")
@click.option("--repo-path", required=True, type=click.Path(exists=True),
              help="Path to the git repository to test.")
@click.option("--effort", type=click.Choice(["low", "standard", "high", "max"]),
              default="standard", show_default=True,
              help="Effort level.")
@click.option("--team", default="full", show_default=True,
              help="Team preset or name.")
@click.option("--allow-dirty", is_flag=True,
              help="Skip the clean git tree check.")
@click.pass_context
def orchestrate_test(
    ctx: click.Context,
    repo_path: str,
    effort: str,
    team: str,
    allow_dirty: bool,
) -> None:
    """Run a comprehensive software testing campaign.

    The agent team will discover features, exercise user flows, probe edge
    cases, and write a test-report.md summarising all findings.
    """
    from ...orchestrator.prompts import TEST_MODE_ORCHESTRATOR_PROMPT

    click.echo(
        click.style("synapse orchestrate test", fg="cyan", bold=True)
        + f"  team={team}  effort={effort}"
    )
    click.echo(f"  repo: {repo_path}")

    engine = _make_engine(ctx, team, effort)

    # Build a structured plan for the test campaign
    plan = GoalPlan(
        context="Comprehensive software testing campaign.",
        stages=[
            GoalStage(
                index=1,
                name="Setup & Discovery",
                description="Understand the system: read the README, list endpoints/commands, identify key user flows.",
                verification="skip",
            ),
            GoalStage(
                index=2,
                name="Feature Walkthroughs",
                description="Exercise every documented feature. Run the test suite and document any failures.",
            ),
            GoalStage(
                index=3,
                name="Edge Cases",
                description="Try unexpected inputs, missing data, concurrent operations, and error conditions.",
            ),
            GoalStage(
                index=4,
                name="Triage & Regression",
                description=(
                    "Summarise all findings in test-report.md. "
                    "Create regression tests for every confirmed bug. "
                    "Assign severity ratings to each finding."
                ),
            ),
        ],
    )

    try:
        result = engine.run(
            goal=TEST_MODE_ORCHESTRATOR_PROMPT,
            repo_path=repo_path,
            plan=plan,
            mode=RunMode.test,
            require_clean_tree=not allow_dirty,
        )
    except RuntimeError as exc:
        click.echo(click.style(f"Error: {exc}", fg="red"), err=True)
        sys.exit(1)

    if result.success:
        click.echo(click.style("  Test campaign completed.", fg="green", bold=True))
    else:
        click.echo(
            click.style(f"  Test campaign failed: {result.error or 'unknown error'}", fg="red"),
            err=True,
        )
        sys.exit(1)


@click.command("improve")
@click.option("--repo-path", required=True, type=click.Path(exists=True),
              help="Path to the git repository to improve.")
@click.option("--effort", type=click.Choice(["low", "standard", "high", "max"]),
              default="standard", show_default=True,
              help="Effort level.")
@click.option("--team", default="full", show_default=True,
              help="Team preset or name.")
@click.option("--allow-dirty", is_flag=True,
              help="Skip the clean git tree check.")
@click.pass_context
def orchestrate_improve(
    ctx: click.Context,
    repo_path: str,
    effort: str,
    team: str,
    allow_dirty: bool,
) -> None:
    """Run a code quality improvement campaign.

    The agent team analyses the codebase across multiple dimensions
    (simplification, architecture, dead code, security, usability), then
    applies safe fixes and writes improve-report.md for anything requiring
    a human decision.
    """
    from ...orchestrator.prompts import IMPROVE_MODE_ORCHESTRATOR_PROMPT

    click.echo(
        click.style("synapse orchestrate improve", fg="cyan", bold=True)
        + f"  team={team}  effort={effort}"
    )
    click.echo(f"  repo: {repo_path}")

    engine = _make_engine(ctx, team, effort)

    # Analysis stages run in parallel (same parallel_group), fix runs after
    plan = GoalPlan(
        context="Code quality improvement campaign.",
        stages=[
            GoalStage(
                index=1,
                name="Simplification Analysis",
                description="Find overly complex code that could be simplified without changing behaviour.",
                parallel_group=1,
                verification="skip",
            ),
            GoalStage(
                index=2,
                name="Architecture Analysis",
                description="Identify structural issues: tight coupling, missing abstractions, inconsistent patterns.",
                parallel_group=1,
                verification="skip",
            ),
            GoalStage(
                index=3,
                name="Dead Weight Analysis",
                description="Find unused code, dead imports, and commented-out blocks safe to remove.",
                parallel_group=1,
                verification="skip",
            ),
            GoalStage(
                index=4,
                name="Security Analysis",
                description="Identify obvious vulnerabilities: hardcoded secrets, injection vectors, missing validation.",
                parallel_group=1,
                verification="skip",
            ),
            GoalStage(
                index=5,
                name="Triage & Fix",
                description=(
                    "Review all analysis reports. Apply safe, unambiguous fixes directly. "
                    "Flag anything requiring a human decision as 'Needs decision' in improve-report.md. "
                    "Auto-commit each batch of safe fixes."
                ),
                persist_changes=True,
            ),
        ],
    )

    try:
        result = engine.run(
            goal=IMPROVE_MODE_ORCHESTRATOR_PROMPT,
            repo_path=repo_path,
            plan=plan,
            mode=RunMode.improve,
            require_clean_tree=not allow_dirty,
        )
    except RuntimeError as exc:
        click.echo(click.style(f"Error: {exc}", fg="red"), err=True)
        sys.exit(1)

    if result.success:
        click.echo(click.style("  Improvement campaign completed.", fg="green", bold=True))
    else:
        click.echo(
            click.style(f"  Improvement campaign failed: {result.error or 'unknown error'}", fg="red"),
            err=True,
        )
        sys.exit(1)


@click.command("resume")
@click.argument("run_id", required=False)
@click.option("--repo-path", required=True, type=click.Path(exists=True),
              help="Path to the git repository (must match the original run).")
@click.option("--allow-dirty", is_flag=True,
              help="Skip the clean git tree check.")
@click.pass_context
def orchestrate_resume(
    ctx: click.Context,
    run_id: Optional[str],
    repo_path: str,
    allow_dirty: bool,
) -> None:
    """Resume a paused or interrupted orchestration run.

    RUN_ID is the UUID (or 8-char prefix) of the run to resume.
    If omitted, the most recent non-completed run is selected.
    """
    config: SynapseConfig = ctx.obj["config"]
    db = Database(config.db_path)

    # Resolve run_id
    if run_id:
        row = db.fetchone(
            "SELECT * FROM runs WHERE id LIKE ? ORDER BY created_at DESC LIMIT 1",
            (f"{run_id}%",),
        )
    else:
        row = db.fetchone(
            "SELECT * FROM runs WHERE status IN ('running', 'paused', 'failed') ORDER BY created_at DESC LIMIT 1"
        )

    if not row:
        click.echo(
            click.style("No resumable run found.", fg="red"),
            err=True,
        )
        sys.exit(1)

    stored_run_id: str = row["id"]
    goal: str = row["goal"] or ""
    team_name: str = row["team_name"] or "full"
    effort_str: str = row["effort"] or "standard"
    mode_str: str = row["mode"] or "goal"

    click.echo(
        click.style("synapse orchestrate resume", fg="cyan", bold=True)
        + f"  run={stored_run_id[:8]}  team={team_name}  effort={effort_str}"
    )
    click.echo(f"  goal: {goal[:120]}{'...' if len(goal) > 120 else ''}")

    # Reconstruct plan from DB stages (if any)
    stage_rows = db.fetchall(
        "SELECT * FROM stages WHERE run_id=? ORDER BY stage_index",
        (stored_run_id,),
    )

    plan: Optional[GoalPlan] = None
    pending_stages: list[GoalStage] = []
    for s in stage_rows:
        if s["status"] in ("pending", "running", "failed"):
            pending_stages.append(
                GoalStage(
                    index=s["stage_index"],
                    name=s["name"] or "",
                    description=s["description"] or "",
                    acceptance_criteria=s["acceptance_criteria"] or "",
                    parallel_group=s["parallel_group"],
                    verification=s["verification"] or "full",
                )
            )

    if pending_stages:
        plan = GoalPlan(stages=pending_stages)

    engine = _make_engine(ctx, team_name, effort_str)
    # Override the run_id so we write into the existing run row
    engine._run_id = stored_run_id

    try:
        result = engine.run(
            goal=goal,
            repo_path=repo_path,
            plan=plan,
            mode=RunMode(mode_str),
            require_clean_tree=not allow_dirty,
        )
    except RuntimeError as exc:
        click.echo(click.style(f"Error: {exc}", fg="red"), err=True)
        sys.exit(1)

    if result.success:
        click.echo(click.style("  Run resumed and completed successfully.", fg="green", bold=True))
    else:
        click.echo(
            click.style(f"  Resume failed: {result.error or 'unknown error'}", fg="red"),
            err=True,
        )
        sys.exit(1)


# ──────────────────────────────────────────────────────────────────────────────
# fix-from — load a prior report and fix issues
# ──────────────────────────────────────────────────────────────────────────────


@click.command("fix-from")
@click.argument("report_path", type=click.Path(exists=True))
@click.option("--repo-path", required=True, type=click.Path(exists=True),
              help="Path to the git repository.")
@click.option("--effort", type=click.Choice(["low", "standard", "high", "max"]),
              default="standard", show_default=True, help="Effort level.")
@click.option("--team", default="full", show_default=True, help="Team preset or name.")
@click.option("--allow-dirty", is_flag=True, help="Skip the clean git tree check.")
@click.pass_context
def orchestrate_fix_from(
    ctx: click.Context,
    report_path: str,
    repo_path: str,
    effort: str,
    team: str,
    allow_dirty: bool,
) -> None:
    """Fix issues from a prior report (test-report.md, improve-report.md, etc.).

    REPORT_PATH is the path to the report file containing issues to fix.
    The agent team will read the report and apply fixes for each issue.
    """
    from pathlib import Path
    from ...orchestrator.prompts import FIX_FROM_ORCHESTRATOR_PROMPT

    report_content = Path(report_path).read_text(encoding="utf-8")
    report_name = Path(report_path).name

    click.echo(
        click.style("synapse orchestrate fix-from", fg="cyan", bold=True)
        + f"  team={team}  effort={effort}"
    )
    click.echo(f"  report: {report_name} ({len(report_content)} chars)")
    click.echo(f"  repo:   {repo_path}")

    engine = _make_engine(ctx, team, effort)

    plan = GoalPlan(
        context=f"Fix issues from {report_name}.",
        stages=[
            GoalStage(
                index=1,
                name="Parse & Prioritize",
                description=(
                    f"Read the report at {report_path}. "
                    "Parse all issues, categorize by severity, and plan fixes."
                ),
                verification="skip",
            ),
            GoalStage(
                index=2,
                name="Apply Fixes",
                description=(
                    "Apply fixes for all high-priority and medium-priority issues. "
                    "Run tests after each fix to verify no regressions. "
                    "Auto-commit each batch of fixes."
                ),
            ),
            GoalStage(
                index=3,
                name="Verify & Report",
                description=(
                    "Run the full test suite to verify all fixes. "
                    "Write a fix-report.md summarizing what was fixed and what remains."
                ),
            ),
        ],
    )

    try:
        result = engine.run(
            goal=FIX_FROM_ORCHESTRATOR_PROMPT.format(
                report_path=report_path,
                report_content=report_content[:3000],
            ),
            repo_path=repo_path,
            plan=plan,
            mode=RunMode.fix_from,
            require_clean_tree=not allow_dirty,
        )
    except RuntimeError as exc:
        click.echo(click.style(f"Error: {exc}", fg="red"), err=True)
        sys.exit(1)

    if result.success:
        click.echo(click.style("  Fix-from campaign completed.", fg="green", bold=True))
    else:
        click.echo(
            click.style(f"  Fix-from failed: {result.error or 'unknown error'}", fg="red"),
            err=True,
        )
        sys.exit(1)


# ──────────────────────────────────────────────────────────────────────────────
# adaptive — dynamically plan stages based on LLM analysis
# ──────────────────────────────────────────────────────────────────────────────


@click.command("adaptive")
@click.argument("goal", required=False)
@click.option("--repo-path", required=True, type=click.Path(exists=True),
              help="Path to the git repository.")
@click.option("--effort", type=click.Choice(["low", "standard", "high", "max"]),
              default="standard", show_default=True, help="Effort level.")
@click.option("--team", default="full", show_default=True, help="Team preset or name.")
@click.option("--allow-dirty", is_flag=True, help="Skip the clean git tree check.")
@click.pass_context
def orchestrate_adaptive(
    ctx: click.Context,
    goal: Optional[str],
    repo_path: str,
    effort: str,
    team: str,
    allow_dirty: bool,
) -> None:
    """Run adaptive orchestration — the LLM dynamically plans stages.

    Unlike fixed-plan modes, adaptive mode lets the orchestrator LLM decide
    how many stages to create and what each stage should do, based on its
    analysis of the codebase and the goal.
    """
    from ...orchestrator.prompts import ADAPTIVE_ORCHESTRATOR_PROMPT

    goal_text = _resolve_goal(goal, None)

    click.echo(
        click.style("synapse orchestrate adaptive", fg="cyan", bold=True)
        + f"  team={team}  effort={effort}"
    )
    click.echo(f"  goal: {goal_text[:120]}{'...' if len(goal_text) > 120 else ''}")
    click.echo(f"  repo: {repo_path}")

    engine = _make_engine(ctx, team, effort)

    # For adaptive mode, we start with a single stage and let the LLM plan dynamically
    plan = GoalPlan(
        context="Adaptive orchestration — stages planned dynamically by the orchestrator LLM.",
        stages=[
            GoalStage(
                index=1,
                name="Analysis & Planning",
                description=(
                    f"Analyze the codebase at {repo_path} and the goal: {goal_text}. "
                    "Create a detailed plan with appropriate stages. "
                    "Report the plan before starting work."
                ),
                verification="skip",
            ),
            GoalStage(
                index=2,
                name="Execution",
                description=(
                    "Execute the plan created in stage 1. "
                    "Break work into focused, verifiable units. "
                    "Report progress after each unit."
                ),
            ),
            GoalStage(
                index=3,
                name="Verification & Completion",
                description=(
                    "Run all tests, verify all changes are correct, "
                    "and write a summary of what was accomplished."
                ),
            ),
        ],
    )

    try:
        result = engine.run(
            goal=ADAPTIVE_ORCHESTRATOR_PROMPT.format(goal=goal_text),
            repo_path=repo_path,
            plan=plan,
            mode=RunMode.goal,
            require_clean_tree=not allow_dirty,
        )
    except RuntimeError as exc:
        click.echo(click.style(f"Error: {exc}", fg="red"), err=True)
        sys.exit(1)

    if result.success:
        click.echo(click.style("  Adaptive run completed.", fg="green", bold=True))
    else:
        click.echo(
            click.style(f"  Adaptive run failed: {result.error or 'unknown error'}", fg="red"),
            err=True,
        )
        sys.exit(1)
