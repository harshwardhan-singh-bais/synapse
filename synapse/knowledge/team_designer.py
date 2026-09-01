"""
Team designer — LLM-driven team composition for orchestration runs.

Uses an LLM to analyse a project description and design an optimal agent
team, including roles, agent backends, worktree branches, and verification
strategy.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from ..db.database import Database
from ..orchestrator.types import AgentConfig, Effort, TeamConfig

log = logging.getLogger(__name__)


class TeamDesigner:
    """Designs orchestration teams using an LLM.

    Given a project description and constraints, the designer produces a
    ``TeamConfig`` that specifies which agents to use, their roles, and
    the verification strategy.
    """

    def __init__(self, db: Database) -> None:
        self.db = db

    # ──────────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────────

    async def design_team(
        self,
        project_description: str,
        available_agents: Optional[list[str]] = None,
        effort: Effort = Effort.standard,
        constraints: str = "",
    ) -> TeamConfig:
        """Design an optimal team composition for a project.

        Args:
            project_description: What the project is about and what needs to be done.
            available_agents: List of agent backend names available (e.g., ["claude", "codex"]).
            effort: The effort level for the run.
            constraints: Any additional constraints (budget, time, preferred agents, etc.).

        Returns:
            A fully configured TeamConfig ready for the orchestrator.
        """
        if available_agents is None:
            available_agents = ["claude"]

        # Build the design prompt
        prompt = self._build_design_prompt(
            project_description, available_agents, effort, constraints
        )

        # Call LLM to design the team
        response = await self._call_llm(prompt)

        # Parse the response into a TeamConfig
        team = self._parse_team_config(response, available_agents, effort)

        log.info(
            "Designed team '%s' with %d agents for project: %s",
            team.name,
            len(team.agents),
            project_description[:100],
        )

        return team

    async def suggest_team_preset(
        self,
        project_type: str,
    ) -> dict:
        """Suggest a team preset for a common project type.

        Returns a dict with 'name', 'description', and 'team' fields.
        """
        prompt = (
            f"# Team Preset Suggestion\n\n"
            f"Project type: {project_type}\n\n"
            f"Suggest a team preset for this type of project.  Include:\n"
            f"1. A short name (lowercase, hyphenated)\n"
            f"2. A one-line description\n"
            f"3. The roles needed and what each does\n"
            f"4. Which agents to use for each role\n\n"
            f"Return as JSON with keys: name, description, roles (array of objects "
            f"with role, agent, description)."
        )

        response = await self._call_llm(prompt)

        try:
            start = response.find("{")
            end = response.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(response[start:end])
        except (json.JSONDecodeError, ValueError):
            pass

        return {
            "name": project_type.lower().replace(" ", "-"),
            "description": f"Team preset for {project_type}",
            "roles": [],
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _build_design_prompt(
        self,
        project_description: str,
        available_agents: list[str],
        effort: Effort,
        constraints: str,
    ) -> str:
        """Build the LLM prompt for team design."""
        effort_guidance = {
            Effort.low: "Keep the team small (2-3 agents).  Focus on speed over thoroughness.",
            Effort.standard: "Use a balanced team (3-5 agents).  Include basic verification.",
            Effort.high: "Use a full team (4-6 agents).  Include dedicated verification roles.",
            Effort.max: "Use the largest team possible (5-8 agents).  Maximize verification coverage.",
        }

        prompt_parts = [
            "# Team Design Task\n",
            "## Project Description\n",
            project_description,
            "",
            "## Available Agents\n",
            ", ".join(available_agents),
            "",
            f"## Effort Level: {effort.value}",
            effort_guidance.get(effort, ""),
            "",
        ]

        if constraints:
            prompt_parts.extend([
                "## Constraints\n",
                constraints,
                "",
            ])

        prompt_parts.extend([
            "## Instructions\n",
            "Design an optimal agent team for this project.  Consider:\n",
            "1. **Roles needed**: architect, backend, frontend, tester, reviewer, etc.",
            "2. **Agent assignment**: which agent backend fits each role best",
            "3. **Worktree isolation**: each role should work in its own branch",
            "4. **Verification strategy**: who verifies whose work",
            "5. **Prompt prefixes**: role-specific instructions for each agent",
            "",
            "## Output Format\n",
            "Return a JSON object with this structure:\n",
            "```json",
            "{",
            '  "name": "team-name",',
            '  "description": "One-line description",',
            '  "agents": {',
            '    "role_name": {',
            '      "backend": "agent_name",',
            '      "description": "What this role does",',
            '      "worktree_branch": "feat/role-name",',
            '      "prompt_prefix": "Role-specific instructions...",',
            '      "timeout_s": 1800',
            "    }",
            "  },",
            '  "verifiers": {',
            '    "testers": ["tester_role"],',
            '    "reviewers": ["reviewer_role"]',
            "  }",
            "}",
            "```",
            "",
            "Return ONLY the JSON object, no other text.",
        ])

        return "\n".join(prompt_parts)

    def _parse_team_config(
        self,
        response: str,
        available_agents: list[str],
        effort: Effort,
    ) -> TeamConfig:
        """Parse an LLM response into a TeamConfig."""
        try:
            # Extract JSON from the response
            start = response.find("{")
            end = response.rfind("}") + 1
            if start >= 0 and end > start:
                data = json.loads(response[start:end])
                return self._dict_to_team_config(data, available_agents, effort)
        except (json.JSONDecodeError, ValueError, KeyError) as exc:
            log.warning("Failed to parse team design response: %s", exc)

        # Fallback: create a minimal team with the first available agent
        return self._default_team(available_agents, effort)

    def _dict_to_team_config(
        self,
        data: dict,
        available_agents: list[str],
        effort: Effort,
    ) -> TeamConfig:
        """Convert a parsed dict into a TeamConfig."""
        agents: dict[str, AgentConfig] = {}

        for role_name, role_data in data.get("agents", {}).items():
            backend = role_data.get("backend", available_agents[0])
            # Ensure the backend is available
            if backend not in available_agents:
                backend = available_agents[0]

            agents[role_name] = AgentConfig(
                name=role_name,
                backend=backend,
                description=role_data.get("description", f"{role_name} agent"),
                worktree_branch=role_data.get("worktree_branch", f"feat/{role_name}"),
                prompt_prefix=role_data.get("prompt_prefix", ""),
                timeout_s=role_data.get("timeout_s", 1800),
            )

        verifiers = data.get("verifiers", {})

        return TeamConfig(
            name=data.get("name", "designed-team"),
            description=data.get("description", "LLM-designed team"),
            agents=agents,
            verifiers=verifiers,
        )

    def _default_team(
        self,
        available_agents: list[str],
        effort: Effort,
    ) -> TeamConfig:
        """Create a default team when LLM parsing fails."""
        agent = available_agents[0] if available_agents else "claude"

        agents = {
            "worker_smart": AgentConfig(
                name="worker_smart",
                backend=agent,
                description="Primary coding agent",
                worktree_branch="feat/main",
            ),
        }

        if effort in (Effort.high, Effort.max):
            agents["architect"] = AgentConfig(
                name="architect",
                backend=agent,
                description="Code reviewer and architect",
                worktree_branch="feat/review",
            )
            agents["tester"] = AgentConfig(
                name="tester",
                backend=agent,
                description="Test runner and verifier",
                worktree_branch="feat/test",
            )

        return TeamConfig(
            name="default-team",
            description="Default team configuration",
            agents=agents,
            verifiers={
                "testers": ["tester"] if "tester" in agents else [],
                "reviewers": ["architect"] if "architect" in agents else [],
            } if effort in (Effort.high, Effort.max) else {},
        )

    async def _call_llm(self, prompt: str) -> str:
        """Call the LLM with a prompt and return the response."""
        import os

        # Determine available models
        models: list[tuple[str, str]] = []
        if os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"):
            key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
            models.append(("gemini-2.0-flash", key))
        if os.environ.get("ANTHROPIC_API_KEY"):
            models.append(("claude-sonnet-4-5-20250514", os.environ["ANTHROPIC_API_KEY"]))
        if os.environ.get("OPENAI_API_KEY"):
            models.append(("gpt-4o", os.environ["OPENAI_API_KEY"]))

        if not models:
            return (
                '{"name": "fallback-team", "description": "No LLM available", '
                '"agents": {"worker_smart": {"backend": "claude", '
                '"description": "Primary coding agent"}}}'
            )

        # Try each model
        for model_name, _ in models:
            try:
                from pydantic_ai import Agent

                agent = Agent(model=model_name, system_prompt=_DESIGNER_SYSTEM_PROMPT)
                import asyncio

                loop = asyncio.new_event_loop()
                try:
                    result = loop.run_until_complete(agent.run(prompt))
                    if hasattr(result, "output"):
                        return str(result.output)
                    elif hasattr(result, "data"):
                        return str(result.data)
                finally:
                    loop.close()
            except Exception as exc:
                log.warning("Team designer LLM error on %s: %s", model_name, exc)
                continue

        return '{"name": "fallback-team", "description": "All LLMs failed"}'


# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

_DESIGNER_SYSTEM_PROMPT = (
    "You are the Synapse team designer.  You analyse project requirements "
    "and design optimal agent teams for autonomous orchestration.  "
    "Always return valid JSON as specified in the prompt.  "
    "Consider agent strengths: Claude for complex reasoning and architecture, "
    "Codex for fast code generation, Cursor for IDE-integrated work, "
    "Gemini for large-context analysis."
)
