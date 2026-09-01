"""
Claude Code session — wraps claude-agent-sdk for direct API or subscription use.

Ported from kodo's sessions/claude.py. Key feature: pops ANTHROPIC_API_KEY
from the environment so the subprocess uses the Claude.ai subscription instead
of billing against the API key.
"""
from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# Lock to prevent race conditions when popping/restoring ANTHROPIC_API_KEY
_anthropic_env_lock = threading.Lock()


@dataclass
class QueryResult:
    """Result from a Claude Code query."""
    text: str = ""
    is_error: bool = False
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    session_id: Optional[str] = None
    duration_secs: float = 0.0


@dataclass
class SessionStats:
    """Session statistics."""
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    last_activity: float = 0.0
    query_count: int = 0

    @property
    def cost_bucket(self) -> str:
        return "claude_subscription"


class ClaudeSession:
    """Claude Code session using claude-agent-sdk.

    Key behavior:
    - Pops ANTHROPIC_API_KEY from env so Claude uses subscription (not API billing)
    - Supports bypassPermissions mode for autonomous operation
    - Handles session resume via session_id
    """

    def __init__(
        self,
        project_dir: Path,
        model: str = "claude-sonnet-4-5-20250514",
        use_api_key: bool = False,
        effort: Optional[str] = None,
        mcp_servers: Optional[list[dict]] = None,
        resume_session_id: Optional[str] = None,
        bypass_permissions: bool = True,
    ) -> None:
        self.project_dir = project_dir
        self.model = model
        self.use_api_key = use_api_key
        self.effort = effort
        self.mcp_servers = mcp_servers or []
        self._resume_session_id = resume_session_id
        self.bypass_permissions = bypass_permissions
        self._stats = SessionStats()
        self._session_id: Optional[str] = None
        self._client = None

    @property
    def stats(self) -> SessionStats:
        return self._stats

    @property
    def cost_bucket(self) -> str:
        return "claude_subscription" if not self.use_api_key else "api"

    @property
    def session_id(self) -> Optional[str]:
        return self._session_id

    def _ensure_client(self) -> None:
        """Initialize the Claude SDK client."""
        if self._client is not None:
            return

        try:
            from claude_agent_sdk import ClaudeSDKClient

            # Pop ANTHROPIC_API_KEY if not using API key (subscription mode)
            env_override = None
            if not self.use_api_key:
                with _anthropic_env_lock:
                    api_key = os.environ.pop("ANTHROPIC_API_KEY", None)
                    if api_key:
                        env_override = {"ANTHROPIC_API_KEY_REMOVED": api_key}

            self._client = ClaudeSDKClient(
                cwd=str(self.project_dir),
                model=self.model,
                bypass_permissions=self.bypass_permissions,
            )

        except ImportError:
            raise RuntimeError(
                "claude-agent-sdk is not installed. "
                "Install it with: pip install claude-agent-sdk"
            )

    def query(
        self,
        prompt: str,
        max_turns: int = 30,
        timeout: float = 1800,
    ) -> QueryResult:
        """Send a query to Claude and wait for the response."""
        self._ensure_client()

        start_time = time.time()

        try:
            # Build query parameters
            kwargs = {
                "prompt": prompt,
                "max_turns": max_turns,
            }

            if self._resume_session_id:
                kwargs["session_id"] = self._resume_session_id

            if self.effort:
                kwargs["effort"] = self.effort

            if self.mcp_servers:
                kwargs["mcp_servers"] = self.mcp_servers

            # Run in a dedicated event loop
            import asyncio

            async def _run():
                result = await self._client.query(**kwargs)
                return result

            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(_run())
            finally:
                loop.close()

            # Extract session ID from result
            if hasattr(result, "session_id"):
                self._session_id = result.session_id

            # Update stats
            duration = time.time() - start_time
            self._stats.last_activity = time.time()
            self._stats.query_count += 1

            text = ""
            if hasattr(result, "output"):
                text = str(result.output)
            elif hasattr(result, "text"):
                text = str(result.text)

            tokens_in = getattr(result, "usage", {}).get("input_tokens", 0) if hasattr(result, "usage") else 0
            tokens_out = getattr(result, "usage", {}).get("output_tokens", 0) if hasattr(result, "usage") else 0

            self._stats.total_tokens += tokens_in + tokens_out

            return QueryResult(
                text=text,
                session_id=self._session_id,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                duration_secs=duration,
            )

        except Exception as exc:
            return QueryResult(
                text=f"[Claude error: {exc}]",
                is_error=True,
                duration_secs=time.time() - start_time,
            )

    def reset(self) -> None:
        """Reset the session (start fresh conversation)."""
        self._session_id = None
        self._client = None

    def terminate(self) -> None:
        """Terminate the session."""
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None

    def clone(self) -> "ClaudeSession":
        """Create a clone that shares the same project but has its own session."""
        return ClaudeSession(
            project_dir=self.project_dir,
            model=self.model,
            use_api_key=self.use_api_key,
            effort=self.effort,
            mcp_servers=self.mcp_servers,
            resume_session_id=self._session_id,
            bypass_permissions=self.bypass_permissions,
        )

    def __enter__(self) -> "ClaudeSession":
        return self

    def __exit__(self, *exc) -> None:
        self.terminate()
