"""
Knowledge orchestrator — LLM-driven knowledge management.

Uses an LLM to answer questions, manage artifacts, and provide intelligent
retrieval over the knowledge base.  Integrates with the existing ArtifactStore
and convergence detection.
"""
from __future__ import annotations

import logging
from typing import Optional

from ..db.database import Database
from .artifacts import Artifact, ArtifactStore

log = logging.getLogger(__name__)


class KnowledgeOrchestrator:
    """LLM-driven orchestrator for the knowledge system.

    Responsibilities:
    - Answer natural-language questions using stored artifacts
    - Suggest new artifacts based on project context
    - Summarise and cross-reference existing knowledge
    - Detect knowledge gaps and recommend what to document
    """

    def __init__(self, db: Database) -> None:
        self.db = db
        self.store = ArtifactStore(db)

    # ──────────────────────────────────────────────────────────────────────────
    # Query interface
    # ──────────────────────────────────────────────────────────────────────────

    async def query(self, question: str, context: str = "") -> str:
        """Answer a natural-language question using stored knowledge artifacts.

        Fetches relevant artifacts, builds a prompt, and calls the LLM to
        synthesise an answer grounded in the stored knowledge.
        """
        # Gather relevant artifacts
        artifacts = self._gather_relevant_artifacts(question)

        if not artifacts:
            return (
                "No relevant knowledge artifacts found for this question. "
                "Consider writing some artifacts first with `synapse knowledge write`."
            )

        # Build context from artifacts
        artifact_block = self._format_artifacts(artifacts)

        # Build the prompt
        prompt_parts = [
            "# Knowledge Query\n",
            f"Question: {question}\n",
        ]
        if context:
            prompt_parts.append(f"Additional context: {context}\n")
        prompt_parts.append(
            "## Relevant Knowledge Artifacts\n\n"
            f"{artifact_block}\n\n"
            "Answer the question using ONLY the information above. "
            "If the artifacts don't contain enough information, say so clearly."
        )

        prompt = "\n".join(prompt_parts)

        # Call LLM
        answer = await self._call_llm(prompt)
        return answer

    async def suggest_artifacts(
        self, project_description: str
    ) -> list[dict[str, str]]:
        """Suggest knowledge artifacts that would be useful for a project.

        Returns a list of dicts with 'key', 'name', and 'description' fields.
        """
        existing = self.store.list_artifacts(limit=100)
        existing_keys = [a.key for a in existing]

        prompt = (
            "# Knowledge Artifact Suggestions\n\n"
            f"Project description:\n{project_description}\n\n"
            f"Existing artifacts ({len(existing_keys)}): "
            f"{', '.join(existing_keys[:20])}{'...' if len(existing_keys) > 20 else ''}\n\n"
            "Suggest 5-10 knowledge artifacts that would be valuable for this project. "
            "For each, provide:\n"
            "- key: a unique identifier (lowercase, hyphenated)\n"
            "- name: a human-readable name\n"
            "- description: what information this artifact should contain\n\n"
            "Return the suggestions as a JSON array."
        )

        response = await self._call_llm(prompt)

        # Parse response (best-effort JSON extraction)
        import json
        try:
            # Try to find a JSON array in the response
            start = response.find("[")
            end = response.rfind("]") + 1
            if start >= 0 and end > start:
                return json.loads(response[start:end])
        except (json.JSONDecodeError, ValueError):
            pass

        return []

    async def summarise(self, keys: Optional[list[str]] = None) -> str:
        """Generate a summary of the knowledge base.

        If *keys* is provided, summarise only those artifacts.
        Otherwise, summarise the entire knowledge base.
        """
        if keys:
            artifacts = [self.store.read(k) for k in keys]
            artifacts = [a for a in artifacts if a is not None]
        else:
            artifacts = self.store.list_artifacts(limit=50)

        if not artifacts:
            return "Knowledge base is empty."

        artifact_block = self._format_artifacts(artifacts)

        prompt = (
            "# Knowledge Base Summary\n\n"
            f"Below are {len(artifacts)} knowledge artifacts:\n\n"
            f"{artifact_block}\n\n"
            "Provide a concise summary of the knowledge base, highlighting:\n"
            "1. Key topics covered\n"
            "2. Notable gaps or missing information\n"
            "3. How the artifacts relate to each other"
        )

        return await self._call_llm(prompt)

    # ──────────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _gather_relevant_artifacts(self, query: str) -> list[Artifact]:
        """Gather artifacts relevant to a query.

        Uses a simple keyword-matching heuristic.  For production use,
        this could be enhanced with embeddings or FTS5 search.
        """
        # Extract keywords from the query (simple split)
        keywords = [
            w.lower()
            for w in query.split()
            if len(w) > 2 and w.lower() not in _STOP_WORDS
        ]

        # Search artifacts by key prefix and content keywords
        all_artifacts = self.store.list_artifacts(limit=200)

        scored: list[tuple[int, Artifact]] = []
        for artifact in all_artifacts:
            score = 0
            key_lower = (artifact.key or "").lower()
            name_lower = (artifact.name or "").lower()
            content_lower = (artifact.content or "").lower()

            for kw in keywords:
                if kw in key_lower:
                    score += 3
                if kw in name_lower:
                    score += 2
                if kw in content_lower:
                    score += 1

            if score > 0:
                scored.append((score, artifact))

        # Sort by score descending, return top 10
        scored.sort(key=lambda x: x[0], reverse=True)
        return [artifact for _, artifact in scored[:10]]

    @staticmethod
    def _format_artifacts(artifacts: list[Artifact]) -> str:
        """Format a list of artifacts into a readable block."""
        parts: list[str] = []
        for a in artifacts:
            content_preview = (a.content or "")[:500]
            if len(a.content or "") > 500:
                content_preview += "..."
            parts.append(
                f"### {a.name or a.key}\n"
                f"**Key:** `{a.key}`\n"
                f"**Type:** {a.mime_type or 'text/plain'}\n\n"
                f"{content_preview}\n"
            )
        return "\n---\n".join(parts)

    async def _call_llm(self, prompt: str) -> str:
        """Call the LLM with a prompt and return the response.

        Tries Gemini Flash first, falls back to other available models.
        """
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
                "[No LLM API key available. Set GOOGLE_API_KEY, ANTHROPIC_API_KEY, "
                "or OPENAI_API_KEY to use the knowledge orchestrator.]"
            )

        # Try each model
        for model_name, _ in models:
            try:
                from pydantic_ai import Agent

                agent = Agent(model=model_name, system_prompt=_KNOWLEDGE_SYSTEM_PROMPT)
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
                log.warning("Knowledge orchestrator LLM error on %s: %s", model_name, exc)
                continue

        return "[All LLM models failed. Check your API keys and try again.]"


# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

_KNOWLEDGE_SYSTEM_PROMPT = (
    "You are the Synapse knowledge orchestrator.  You help users manage "
    "and query a knowledge base of project artifacts.  Always ground your "
    "answers in the provided artifacts.  If the artifacts don't contain "
    "enough information, say so clearly rather than guessing."
)

_STOP_WORDS = {
    "the", "is", "in", "it", "to", "and", "a", "of", "for", "on", "with",
    "that", "this", "are", "was", "be", "have", "has", "had", "but", "not",
    "you", "we", "they", "can", "will", "do", "does", "did", "should",
    "would", "could", "may", "might", "what", "how", "when", "where",
    "which", "who", "whom", "why", "all", "each", "every", "some", "any",
}
