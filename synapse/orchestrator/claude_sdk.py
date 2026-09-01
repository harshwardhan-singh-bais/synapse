"""
Claude Code SDK session integration for the Synapse orchestrator.

Provides direct integration with Claude's SDK for more powerful orchestration.
This allows the orchestrator to use Claude's API directly rather than going
through tmux sessions.

Requires:
- anthropic Python package
- ANTHROPIC_API_KEY environment variable or config
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

log = logging.getLogger(__name__)

# Try to import anthropic
try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False


# ──────────────────────────────────────────────────────────────────────────────
# Claude SDK session configuration
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class ClaudeSDKConfig:
    """Configuration for Claude Code SDK session."""
    model: str = "claude-sonnet-4-5-20250514"
    api_key: Optional[str] = None
    max_tokens: int = 4096
    temperature: float = 0.7
    system_prompt: str = ""
    timeout: float = 120.0
    max_retries: int = 3

    def __post_init__(self):
        if not self.api_key:
            self.api_key = os.environ.get("ANTHROPIC_API_KEY")


# ──────────────────────────────────────────────────────────────────────────────
# Claude SDK session
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class ClaudeMessage:
    """A message in a Claude conversation."""
    role: str  # "user" or "assistant"
    content: str
    timestamp: float = field(default_factory=time.time)


class ClaudeSDKSession:
    """
    Claude Code SDK session.

    Provides a direct interface to Claude's API for orchestration.
    Maintains conversation history for context continuity.
    """

    def __init__(self, config: Optional[ClaudeSDKConfig] = None) -> None:
        if not HAS_ANTHROPIC:
            raise RuntimeError(
                "anthropic package not installed. "
                "Install with: pip install anthropic"
            )

        self.config = config or ClaudeSDKConfig()
        self._client: Optional[anthropic.Anthropic] = None
        self._conversation: list[ClaudeMessage] = []
        self._total_tokens_used = 0
        self._total_cost = 0.0

    def _get_client(self) -> anthropic.Anthropic:
        """Get or create the Anthropic client."""
        if self._client is None:
            if not self.config.api_key:
                raise RuntimeError(
                    "No Anthropic API key configured. "
                    "Set ANTHROPIC_API_KEY environment variable or pass api_key to config."
                )
            self._client = anthropic.Anthropic(api_key=self.config.api_key)
        return self._client

    def send(
        self,
        message: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """
        Send a message to Claude and get a response.

        Args:
            message: The user message to send.
            system_prompt: Optional system prompt override.
            temperature: Optional temperature override.
            max_tokens: Optional max tokens override.

        Returns:
            Claude's response as a string.
        """
        client = self._get_client()

        # Add user message to conversation
        self._conversation.append(ClaudeMessage(role="user", content=message))

        # Build messages list
        messages = [{"role": msg.role, "content": msg.content} for msg in self._conversation]

        # Use provided or default parameters
        sys_prompt = system_prompt or self.config.system_prompt
        temp = temperature if temperature is not None else self.config.temperature
        tokens = max_tokens or self.config.max_tokens

        try:
            # Make API call
            response = client.messages.create(
                model=self.config.model,
                max_tokens=tokens,
                temperature=temp,
                system=sys_prompt if sys_prompt else anthropic.NOT_GIVEN,
                messages=messages,
            )

            # Extract response text
            assistant_message = ""
            for block in response.content:
                if hasattr(block, "text"):
                    assistant_message += block.text

            # Add assistant message to conversation
            self._conversation.append(ClaudeMessage(
                role="assistant",
                content=assistant_message,
            ))

            # Track token usage
            if hasattr(response, "usage"):
                self._total_tokens_used += response.usage.input_tokens + response.usage.output_tokens

            return assistant_message

        except anthropic.RateLimitError as exc:
            log.warning("Claude rate limit hit: %s", exc)
            raise
        except anthropic.APIError as exc:
            log.error("Claude API error: %s", exc)
            raise

    def send_with_tools(
        self,
        message: str,
        tools: list[dict[str, Any]],
        system_prompt: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Send a message with tool definitions.

        Args:
            message: The user message to send.
            tools: List of tool definitions.
            system_prompt: Optional system prompt override.

        Returns:
            Dictionary with response and any tool calls.
        """
        client = self._get_client()

        self._conversation.append(ClaudeMessage(role="user", content=message))

        messages = [{"role": msg.role, "content": msg.content} for msg in self._conversation]
        sys_prompt = system_prompt or self.config.system_prompt

        try:
            response = client.messages.create(
                model=self.config.model,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
                system=sys_prompt if sys_prompt else anthropic.NOT_GIVEN,
                messages=messages,
                tools=tools,
            )

            # Process response
            result = {
                "text": "",
                "tool_calls": [],
                "stop_reason": response.stop_reason,
            }

            for block in response.content:
                if hasattr(block, "text"):
                    result["text"] += block.text
                elif hasattr(block, "type") and block.type == "tool_use":
                    result["tool_calls"].append({
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    })

            # Add assistant message to conversation
            self._conversation.append(ClaudeMessage(
                role="assistant",
                content=result["text"],
            ))

            # Track tokens
            if hasattr(response, "usage"):
                self._total_tokens_used += response.usage.input_tokens + response.usage.output_tokens

            return result

        except Exception as exc:
            log.error("Claude tool call error: %s", exc)
            raise

    def clear_conversation(self) -> None:
        """Clear the conversation history."""
        self._conversation.clear()

    def get_conversation(self) -> list[ClaudeMessage]:
        """Get the conversation history."""
        return self._conversation.copy()

    @property
    def total_tokens_used(self) -> int:
        """Get total tokens used in this session."""
        return self._total_tokens_used

    def is_available(self) -> bool:
        """Check if the Claude SDK is available and configured."""
        return (
            HAS_ANTHROPIC
            and self.config.api_key is not None
        )


# ──────────────────────────────────────────────────────────────────────────────
# Claude SDK orchestrator integration
# ──────────────────────────────────────────────────────────────────────────────


class ClaudeSDKOrchestrator:
    """
    Orchestrator that uses Claude's SDK directly.

    Provides more powerful orchestration by using Claude's API directly
    rather than going through tmux sessions.
    """

    def __init__(self, config: Optional[ClaudeSDKConfig] = None) -> None:
        self.config = config or ClaudeSDKConfig()
        self._session: Optional[ClaudeSDKSession] = None

    def _get_session(self) -> ClaudeSDKSession:
        """Get or create the Claude session."""
        if self._session is None:
            self._session = ClaudeSDKSession(self.config)
        return self._session

    def plan(self, goal: str, context: str = "") -> dict[str, Any]:
        """
        Use Claude to plan the implementation of a goal.

        Args:
            goal: The high-level goal to plan.
            context: Additional context about the project.

        Returns:
            Dictionary with the plan stages and details.
        """
        session = self._get_session()

        system_prompt = """You are an expert software architect and project planner.
Your job is to break down complex goals into actionable implementation stages.

Respond with a JSON object containing:
{
    "stages": [
        {
            "name": "Stage name",
            "description": "What this stage accomplishes",
            "tasks": ["task1", "task2"],
            "dependencies": ["stage_name_if_any"]
        }
    ],
    "estimated_complexity": "low|medium|high",
    "risks": ["risk1", "risk2"]
}

Be specific and actionable. Each stage should be completable in one session."""

        prompt = f"""Goal: {goal}

Context:
{context if context else "No additional context provided."}

Please create a detailed implementation plan."""

        response = session.send(prompt, system_prompt=system_prompt)

        # Try to parse JSON response
        try:
            # Find JSON in response (may be wrapped in markdown)
            json_start = response.find("{")
            json_end = response.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                plan_json = response[json_start:json_end]
                return json.loads(plan_json)
        except json.JSONDecodeError:
            pass

        # Fallback: return the text response
        return {
            "stages": [{"name": "Implementation", "description": response, "tasks": []}],
            "estimated_complexity": "unknown",
            "risks": [],
        }

    def review_code(self, code: str, language: str = "python") -> dict[str, Any]:
        """
        Use Claude to review code.

        Args:
            code: The code to review.
            language: The programming language.

        Returns:
            Dictionary with review findings.
        """
        session = self._get_session()

        system_prompt = """You are an expert code reviewer.
Analyze the provided code and give feedback on:
- Bugs or potential issues
- Performance concerns
- Security vulnerabilities
- Code style and best practices
- Suggestions for improvement

Respond with a JSON object:
{
    "issues": [
        {
            "severity": "critical|high|medium|low",
            "line": 42,
            "description": "Issue description",
            "suggestion": "How to fix it"
        }
    ],
    "overall_quality": "excellent|good|fair|poor",
    "summary": "Brief summary of findings"
}"""

        prompt = f"""Please review this {language} code:

```{language}
{code}
```"""

        response = session.send(prompt, system_prompt=system_prompt)

        try:
            json_start = response.find("{")
            json_end = response.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                return json.loads(response[json_start:json_end])
        except json.JSONDecodeError:
            pass

        return {
            "issues": [],
            "overall_quality": "unknown",
            "summary": response,
        }

    def generate_tests(self, code: str, language: str = "python") -> str:
        """
        Use Claude to generate tests for code.

        Args:
            code: The code to generate tests for.
            language: The programming language.

        Returns:
            Generated test code as a string.
        """
        session = self._get_session()

        system_prompt = f"""You are an expert test engineer.
Generate comprehensive tests for the provided {language} code.
Include unit tests, edge cases, and integration tests where appropriate.
Use standard testing frameworks for {language}."""

        prompt = f"""Generate tests for this {language} code:

```{language}
{code}
```"""

        return session.send(prompt, system_prompt=system_prompt)

    def explain_code(self, code: str, language: str = "python") -> str:
        """
        Use Claude to explain code.

        Args:
            code: The code to explain.
            language: The programming language.

        Returns:
            Explanation of the code.
        """
        session = self._get_session()

        system_prompt = """You are an expert programmer and teacher.
Explain the provided code in a clear, educational manner.
Cover:
- What the code does
- How it works
- Key concepts used
- Any interesting patterns or techniques"""

        prompt = f"""Explain this {language} code:

```{language}
{code}
```"""

        return session.send(prompt, system_prompt=system_prompt)

    @property
    def is_available(self) -> bool:
        """Check if Claude SDK is available."""
        return HAS_ANTHROPIC and bool(self.config.api_key)
