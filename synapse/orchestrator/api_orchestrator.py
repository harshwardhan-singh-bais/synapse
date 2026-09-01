"""
LLM-driven orchestration engine using pydantic-ai.

The orchestrator is an LLM (Gemini Flash default, Claude API alternative)
that plans stages and calls tools to delegate work to agent sessions.
Each tool call creates/reuses a tmux session, sends a prompt, and waits
for the agent to finish.

This is the port of kodo's ApiOrchestrator into Synapse's architecture.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from ..core.config import SynapseConfig
from ..db.database import Database
from ..session.manager import SessionManager
from .engine import OrchestrationEngine
from .prompts import (
    EFFORT_SUPPLEMENTS,
    ORCHESTRATOR_BASE_PROMPT,
    VERIFICATION_EFFORT_SUPPLEMENTS,
)
from .run_log import RunLogger
from .subscription import SubscriptionManager
from .types import (
    CycleResult,
    DoneSignal,
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

log = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Rate limit handling — model fallback chain
# ──────────────────────────────────────────────────────────────────────────────

# Models in priority order; the orchestrator tries each one when a 529 (rate
# limit) or other transient API error is encountered.
_MODEL_FALLBACK_CHAIN: list[str] = [
    "gemini-2.0-flash",
    "claude-sonnet-4-5-20250514",
    "gpt-4o",
]

# HTTP status codes that trigger a model fallback
_RETRYABLE_STATUS_CODES = {429, 529, 503}


# ──────────────────────────────────────────────────────────────────────────────
# DoneSignal — shared mutable state between tool handlers and the cycle loop
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class _DoneState:
    """Mutable state shared between the LLM tool handlers and the cycle loop."""

    called: bool = False
    terminal: str = "end_cycle"  # 'goal_done' | 'end_cycle' | 'raise_issue'
    summary: str = ""
    success: bool = False


# ──────────────────────────────────────────────────────────────────────────────
# LLM Orchestrator
# ──────────────────────────────────────────────────────────────────────────────


class ApiOrchestrator(OrchestrationEngine):
    """Orchestrator driven by an LLM via pydantic-ai.

    Overrides ``_run_cycle`` to use an LLM that calls tools:
    - ``ask_worker_fast`` / ``ask_worker_smart`` → dispatch to worker agents
    - ``ask_architect`` → code review (read-only)
    - ``ask_tester`` → end-to-end testing (read-only)
    - ``done`` → signal cycle completion (triggers verification)

    The LLM never touches code directly. It delegates everything through
    tool calls that create tmux sessions and wait for agent output.
    """

    def __init__(
        self,
        db: Database,
        session_mgr: SessionManager,
        team: TeamConfig,
        effort: Effort = Effort.standard,
        config: Optional[SynapseConfig] = None,
    ) -> None:
        super().__init__(db, session_mgr, team, effort, config)
        self._model_name: str = "gemini-2.0-flash"
        self._api_key: Optional[str] = None
        self._done_state = _DoneState()
        # Session reuse: role → session_id (for conversation continuity within a cycle)
        self._role_sessions: dict[str, str] = {}
        # Available API keys for fallback chain
        self._available_api_keys: dict[str, Optional[str]] = {}
        # Subscription manager for key rotation
        self._subscription = SubscriptionManager(db)

    def _configure_model(self) -> None:
        """Detect available API keys and select the orchestrator model.

        Uses the SubscriptionManager to pop keys from the pool, with
        fallback to environment variables.
        """
        import os

        # Try to pop keys from the subscription pool
        google_key = self._subscription.pop_key("google")
        anthropic_key = self._subscription.pop_key("anthropic")
        openai_key = self._subscription.pop_key("openai")

        # Fallback to env vars if no DB keys
        if not google_key:
            google_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
        if not anthropic_key:
            anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
        if not openai_key:
            openai_key = os.environ.get("OPENAI_API_KEY")

        # Collect available API keys for the fallback chain
        self._available_api_keys = {
            "gemini-2.0-flash": google_key,
            "claude-sonnet-4-5-20250514": anthropic_key,
            "gpt-4o": openai_key,
        }

        # Priority: user override > Gemini > Claude > OpenAI
        override = os.environ.get("SYNAPSE_ORCHESTRATOR_MODEL")
        if override:
            self._model_name = override
            self._api_key = self._available_api_keys.get(override)
            return

        if google_key:
            self._model_name = "gemini-2.0-flash"
            self._api_key = google_key
        elif anthropic_key:
            self._model_name = "claude-sonnet-4-5-20250514"
            self._api_key = anthropic_key
        elif openai_key:
            self._model_name = "gpt-4o"
            self._api_key = openai_key
        else:
            # No API key found — fall back to base engine (tmux-only)
            log.warning(
                "No API key found (GOOGLE_API_KEY, ANTHROPIC_API_KEY, OPENAI_API_KEY). "
                "Falling back to direct worker dispatch (no LLM orchestration)."
            )
            self._model_name = ""

    # ──────────────────────────────────────────────────────────────────────────
    # Cycle execution (LLM-driven)
    # ──────────────────────────────────────────────────────────────────────────

    def _run_cycle(
        self,
        goal: str,
        cwd: str,
        cycle_index: int,
        prior_summary: str,
        stage: GoalStage,
    ) -> CycleResult:
        """Execute one orchestrator cycle using an LLM with tools.

        If no API key is available, falls back to the base engine's
        direct worker dispatch.
        """
        self._configure_model()

        if not self._model_name:
            # No API key — use base engine's simple dispatch
            return super()._run_cycle(goal, cwd, cycle_index, prior_summary, stage)

        return self._run_llm_cycle(goal, cwd, cycle_index, prior_summary, stage)

    def _run_llm_cycle(
        self,
        goal: str,
        cwd: str,
        cycle_index: int,
        prior_summary: str,
        stage: GoalStage,
    ) -> CycleResult:
        """Run a cycle using the LLM orchestrator with tool calls.

        Includes automatic model fallback on rate-limit (429/529) and
        transient API errors (503).  The orchestrator tries each model
        in ``_MODEL_FALLBACK_CHAIN`` before giving up.
        """
        from pydantic_ai import Agent

        # Reset done state for this cycle
        self._done_state = _DoneState()
        self._role_sessions.clear()

        # Build the orchestrator system prompt
        system_prompt = self._build_orchestrator_prompt(stage)

        # Build tools
        tools = self._build_tools(cwd)

        # Build the user prompt
        user_prompt = self._build_cycle_prompt(goal, cwd, prior_summary)

        # Determine the model list to try (primary + fallbacks)
        models_to_try = self._get_model_chain()

        # Run the LLM with fallback
        exchanges = 0
        summary = ""
        last_error: Optional[Exception] = None

        for model_name in models_to_try:
            try:
                agent = Agent(
                    model=model_name,
                    system_prompt=system_prompt,
                    tools=tools,
                )

                import asyncio

                loop = asyncio.new_event_loop()
                try:
                    result = loop.run_until_complete(
                        agent.run(user_prompt)
                    )
                    # Extract the final text response
                    if hasattr(result, "output"):
                        summary = str(result.output)[:500]
                    elif hasattr(result, "data"):
                        summary = str(result.data)[:500]
                    exchanges = 1
                    # Success — no need to try more models
                    break
                finally:
                    loop.close()

            except Exception as exc:
                last_error = exc
                if self._is_retryable_error(exc):
                    log.warning(
                        "Rate limit / transient error on %s (%s), "
                        "trying next model...",
                        model_name, exc,
                    )
                    # Mark the key as errored for future rotation
                    self._mark_key_error(model_name, exc)
                    continue
                else:
                    # Non-retryable error — stop trying
                    log.error("LLM orchestrator error on %s: %s", model_name, exc)
                    summary = f"[LLM error: {exc}]"
                    break

        # If we exhausted all models with retryable errors
        if not summary and last_error:
            log.error(
                "All models exhausted after rate limits. Last error: %s", last_error
            )
            summary = f"[All models rate-limited: {last_error}]"

        # Check if done() was called
        if self._done_state.called:
            return CycleResult(
                cycle_index=cycle_index,
                exchanges=exchanges,
                summary=self._done_state.summary or summary,
                finished=True,
                success=self._done_state.success,
            )

        # LLM responded without calling done() — treat as in-progress
        return CycleResult(
            cycle_index=cycle_index,
            exchanges=exchanges,
            summary=summary or "LLM responded without calling done()",
            finished=False,
            success=False,
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Rate limit / fallback helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _get_model_chain(self) -> list[str]:
        """Return an ordered list of models to try, starting with the primary.

        Models without a corresponding API key are skipped.
        """
        chain = [self._model_name]
        for m in _MODEL_FALLBACK_CHAIN:
            if m == self._model_name:
                continue
            # Skip models whose API key is not available
            if self._available_api_keys and not self._available_api_keys.get(m):
                log.debug("Skipping fallback model %s — no API key available", m)
                continue
            chain.append(m)
        return chain

    @staticmethod
    def _is_retryable_error(exc: Exception) -> bool:
        """Return True if *exc* represents a rate-limit or transient API error."""
        msg = str(exc).lower()
        # Check for status code patterns in the exception message
        for code in _RETRYABLE_STATUS_CODES:
            if str(code) in msg:
                return True
        # Check for common rate-limit keywords
        if any(kw in msg for kw in ("rate limit", "too many requests", "529", "429")):
            return True
        # Check for pydantic-ai / httpx specific error attributes
        if hasattr(exc, "status_code") and exc.status_code in _RETRYABLE_STATUS_CODES:  # type: ignore[union-attr]
            return True
        if hasattr(exc, "response") and hasattr(exc.response, "status_code"):  # type: ignore[union-attr]
            if exc.response.status_code in _RETRYABLE_STATUS_CODES:  # type: ignore[union-attr]
                return True
        return False

    def _mark_key_error(self, model_name: str, exc: Exception) -> None:
        """Mark the current key for a model as errored in the subscription pool."""
        provider_map = {
            "gemini-2.0-flash": "google",
            "claude-sonnet-4-5-20250514": "anthropic",
            "gpt-4o": "openai",
        }
        provider = provider_map.get(model_name)
        if provider:
            self._subscription.mark_error(provider)

    # ──────────────────────────────────────────────────────────────────────────
    # Tool builders
    # ──────────────────────────────────────────────────────────────────────────

    def _build_tools(self, cwd: str) -> list:
        """Build the tool functions for the pydantic-ai agent."""
        from pydantic_ai.tools import Tool

        tools = []

        # ask_worker_fast tool
        def ask_worker_fast(task: str) -> str:
            """Delegate a simple, quick coding task to the fast worker agent.
            Use for straightforward implementations, small fixes, mechanical changes."""
            return self._call_agent_tool("worker_fast", task, cwd)

        tools.append(Tool(ask_worker_fast))

        # ask_worker_smart tool
        def ask_worker_smart(task: str) -> str:
            """Delegate a complex coding task to the smart worker agent.
            Use for architecture decisions, debugging, complex features, refactoring."""
            return self._call_agent_tool("worker_smart", task, cwd)

        tools.append(Tool(ask_worker_smart))

        # ask_architect tool
        def ask_architect(task: str) -> str:
            """Ask the architect to review code or design. Read-only — cannot write code.
            Use for code review, architecture analysis, security audit."""
            return self._call_agent_tool("architect", task, cwd)

        tools.append(Tool(ask_architect))

        # ask_tester tool
        def ask_tester(task: str) -> str:
            """Ask the tester to run tests or verify functionality. Read-only — cannot fix.
            Use for running test suites, exercising features, edge case testing."""
            return self._call_agent_tool("tester", task, cwd)

        tools.append(Tool(ask_tester))

        # done tool
        def done(summary: str, success: bool = True) -> str:
            """Signal that the current stage/cycle is complete.
            This triggers independent verification by the architect and tester.
            Call this when you believe the goal has been achieved.
            Args:
                summary: A concise summary of what was accomplished.
                success: Whether the work was completed successfully.
            """
            self._done_state.called = True
            self._done_state.summary = summary
            self._done_state.success = success
            self._done_state.terminal = "goal_done" if success else "raise_issue"
            return f"Done signal received. Summary: {summary[:200]}"

        tools.append(Tool(done))

        return tools

    def _call_agent_tool(self, role: str, prompt: str, cwd: str) -> str:
        """Dispatch a tool call to an agent session.

        Creates or reuses a tmux session for the role, sends the prompt,
        and waits for completion.
        """
        agent_cfg = self.team.agents.get(role)
        if not agent_cfg:
            return f"[No {role} agent configured in team '{self.team.name}']"

        self._logger.agent_call(role, prompt[:200])

        # Reuse session if we already have one for this role
        session_id = self._role_sessions.get(role)

        if session_id and self.session_mgr.get_session(session_id):
            # Reuse existing session — just send the new prompt
            try:
                self.session_mgr.send_text(session_id, prompt)
                output = self._wait_for_agent(session_id, timeout=agent_cfg.timeout_s)
                self._logger.agent_result(role, output[:200])
                return output
            except Exception as exc:
                log.warning("Reuse failed for %s, creating new session: %s", role, exc)

        # Create a new session
        session_name = f"synapse-{self._run_id[:8]}-{role}-{uuid.uuid4().hex[:6]}"
        try:
            session = self.session_mgr.create_session(
                name=session_name,
                repo_path=cwd,
                agent=agent_cfg.backend,
                tag="synapse-run",
            )
            self._role_sessions[role] = session.id
            self.session_mgr.send_text(session.id, prompt)

            output = self._wait_for_agent(session.id, timeout=agent_cfg.timeout_s)
            self._logger.agent_result(role, output[:200])
            return output

        except Exception as exc:
            err = f"[Agent error: {exc}]"
            self._logger.agent_result(role, err)
            return err

    # ──────────────────────────────────────────────────────────────────────────
    # Orchestrator prompt
    # ──────────────────────────────────────────────────────────────────────────

    def _build_orchestrator_prompt(self, stage: GoalStage) -> str:
        """Build the system prompt for the LLM orchestrator."""
        parts = [ORCHESTRATOR_BASE_PROMPT]

        # Role descriptions
        parts.append("\n## Your team:")
        for role, cfg in self.team.agents.items():
            parts.append(f"- **{role}** ({cfg.backend}): {cfg.description}")

        # Effort guidance
        effort_supp = EFFORT_SUPPLEMENTS.get(self.effort.value, "")
        if effort_supp:
            parts.append(f"\n## Effort level: {self.effort.value}")
            parts.append(effort_supp)

        # Verification guidance
        if self.effort in (Effort.high, Effort.max):
            ver_supp = VERIFICATION_EFFORT_SUPPLEMENTS.get(self.effort.value, "")
            if ver_supp:
                parts.append(f"\n## Verification standards: {ver_supp}")

        # Verifier roles
        if self.team.verifiers:
            parts.append("\n## Verification:")
            for role_name in self.team.verifiers.get("testers", []):
                if role_name in self.team.agents:
                    parts.append(f"- Tester: {role_name} — runs tests, exercises features")
            for role_name in self.team.verifiers.get("reviewers", []):
                if role_name in self.team.agents:
                    parts.append(f"- Reviewer: {role_name} — code review, architecture check")

        parts.append("\n## Rules:")
        parts.append("- Never touch code directly — always delegate to agents via tools")
        parts.append("- A stage is ONLY complete when you call done() and verification passes")
        parts.append("- On verification rejection, fix the issues and try again")
        parts.append("- Keep a mental model of what each agent has done")
        parts.append("- Call done(summary, success=True) when you believe the goal is achieved")
        parts.append("- Call done(summary, success=False) if you cannot complete the goal")

        return "\n".join(parts)
