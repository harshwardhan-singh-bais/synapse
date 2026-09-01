"""
Team factory — builds TeamConfig from JSON files or built-in presets.

Lookup order for a named team:
  1. {project}/.synapse/team.json
  2. ~/.config/synapse/teams/{name}.json
  3. Built-in preset ("full", "quick", "test")
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Optional

from ..core.paths import CONFIG_DIR
from .prompts import ARCHITECT_PROMPT, TESTER_PROMPT, WORKER_SYSTEM_PROMPT
from .types import AgentConfig, TeamConfig


# ──────────────────────────────────────────────────────────────────────────────
# Backend detection
# ──────────────────────────────────────────────────────────────────────────────


def _detect_backend() -> str:
    """Return the best available backend CLI: claude > cursor > codex > gemini-cli."""
    _cmd_map = {
        "claude": "claude",
        "cursor": "cursor",
        "codex": "codex",
        "gemini-cli": "gemini",
    }
    for backend, cmd in _cmd_map.items():
        if shutil.which(cmd):
            return backend
    return "claude"  # always try claude as fallback


# ──────────────────────────────────────────────────────────────────────────────
# JSON parsing
# ──────────────────────────────────────────────────────────────────────────────


def team_from_json(data: dict[str, object]) -> TeamConfig:
    """Parse a team JSON dict into a :class:`TeamConfig`."""
    agents: dict[str, AgentConfig] = {}
    for role, cfg in data.get("agents", {}).items():
        agents[role] = AgentConfig(
            role=role,
            backend=cfg.get("backend", "claude"),
            model=cfg.get("model", ""),
            description=cfg.get("description", ""),
            system_prompt=cfg.get("system_prompt", ""),
            max_turns=cfg.get("max_turns", 30),
            timeout_s=cfg.get("timeout_s", 1800),
            session_timeout_s=cfg.get("session_timeout_s", 7200),
        )

    verifiers: dict[str, list[str]] = data.get("verifiers", {
        "testers": ["tester"],
        "reviewers": ["architect"],
    })

    return TeamConfig(
        name=data.get("name", "custom"),
        agents=agents,
        verifiers=verifiers,
        orchestrator_prompt=data.get("orchestrator_prompt", ""),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Built-in presets
# ──────────────────────────────────────────────────────────────────────────────


def _model_variants(backend: str) -> tuple[str, str]:
    """Return (fast_model, smart_model) for a given backend."""
    _variants: dict[str, tuple[str, str]] = {
        "claude": ("claude-haiku-4-5", "claude-sonnet-4-5"),
        "cursor": ("gpt-4o-mini", "gpt-4o"),
        "codex": ("gpt-4o-mini", "gpt-4o"),
        "gemini-cli": ("gemini-2.0-flash", "gemini-2.5-pro"),
    }
    return _variants.get(backend, ("fast", "smart"))


def _builtin_full(backend: str) -> TeamConfig:
    """'full' preset: worker_fast, worker_smart, tester, architect."""
    fast_model, smart_model = _model_variants(backend)
    return TeamConfig(
        name="full",
        agents={
            "worker_fast": AgentConfig(
                role="worker_fast",
                backend=backend,
                model=fast_model,
                description="Fast worker for simple, mechanical coding tasks",
                system_prompt=WORKER_SYSTEM_PROMPT,
                max_turns=20,
                timeout_s=900,
            ),
            "worker_smart": AgentConfig(
                role="worker_smart",
                backend=backend,
                model=smart_model,
                description="Smart worker for complex reasoning, debugging, and architecture tasks",
                system_prompt=WORKER_SYSTEM_PROMPT,
                max_turns=40,
                timeout_s=1800,
            ),
            "tester": AgentConfig(
                role="tester",
                backend=backend,
                model=smart_model,
                description="End-to-end tester; verifies correctness but does not fix bugs",
                system_prompt=TESTER_PROMPT,
                max_turns=30,
                timeout_s=1200,
            ),
            "architect": AgentConfig(
                role="architect",
                backend=backend,
                model=smart_model,
                description="Senior architect reviewer; reviews code but does not write it",
                system_prompt=ARCHITECT_PROMPT,
                max_turns=20,
                timeout_s=900,
            ),
        },
        verifiers={
            "testers": ["tester"],
            "reviewers": ["architect"],
        },
    )


def _builtin_quick(backend: str) -> TeamConfig:
    """'quick' preset: worker_fast + worker_smart only, no verification pass."""
    fast_model, smart_model = _model_variants(backend)
    return TeamConfig(
        name="quick",
        agents={
            "worker_fast": AgentConfig(
                role="worker_fast",
                backend=backend,
                model=fast_model,
                description="Fast worker for simple, mechanical coding tasks",
                system_prompt=WORKER_SYSTEM_PROMPT,
                max_turns=20,
                timeout_s=900,
            ),
            "worker_smart": AgentConfig(
                role="worker_smart",
                backend=backend,
                model=smart_model,
                description="Smart worker for complex reasoning, debugging, and architecture tasks",
                system_prompt=WORKER_SYSTEM_PROMPT,
                max_turns=40,
                timeout_s=1800,
            ),
        },
        # No verifiers — stages complete without an independent verification pass
        verifiers={},
    )


def _builtin_test(backend: str) -> TeamConfig:
    """'test' preset: worker_smart + tester only."""
    _, smart_model = _model_variants(backend)
    return TeamConfig(
        name="test",
        agents={
            "worker_smart": AgentConfig(
                role="worker_smart",
                backend=backend,
                model=smart_model,
                description="Smart worker for fixing issues discovered during testing",
                system_prompt=WORKER_SYSTEM_PROMPT,
                max_turns=40,
                timeout_s=1800,
            ),
            "tester": AgentConfig(
                role="tester",
                backend=backend,
                model=smart_model,
                description="End-to-end tester; verifies correctness but does not fix bugs",
                system_prompt=TESTER_PROMPT,
                max_turns=30,
                timeout_s=1200,
            ),
        },
        verifiers={
            "testers": ["tester"],
            "reviewers": [],
        },
    )


# Registry of all built-in preset factories
_BUILTIN_FACTORIES = {
    "full": _builtin_full,
    "quick": _builtin_quick,
    "test": _builtin_test,
}


# ──────────────────────────────────────────────────────────────────────────────
# Main loader
# ──────────────────────────────────────────────────────────────────────────────


def load_team(name: str, project_dir: Optional[Path] = None) -> TeamConfig:
    """Load a team by name following the lookup hierarchy.

    1. ``{project_dir}/.synapse/team.json`` (project-local override)
    2. ``~/.config/synapse/teams/{name}.json`` (user-level custom teams)
    3. Built-in preset (``full`` / ``quick`` / ``test``)
    """
    # 1. Project-local override
    if project_dir is not None:
        local_path = project_dir / ".synapse" / "team.json"
        if local_path.exists():
            with local_path.open() as fh:
                data = json.load(fh)
            if data.get("name", name) == name or name == data.get("name"):
                return team_from_json(data)

    # 2. User-level custom team file
    user_team_path = CONFIG_DIR / "teams" / f"{name}.json"
    if user_team_path.exists():
        with user_team_path.open() as fh:
            data = json.load(fh)
        return team_from_json(data)

    # 3. Built-in preset
    backend = _detect_backend()
    factory = _BUILTIN_FACTORIES.get(name)
    if factory is not None:
        return factory(backend)

    # Fall back to "full" if the requested name is unknown
    return _builtin_full(backend)
