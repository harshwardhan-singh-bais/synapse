"""Identity system — process binding, session binding, and CVCV name allocation."""

from .bindings import (
    BindingManager,
    ClaudeActorConfig,
    ClaudeCapability,
    CLAUDE_ACTOR_PROFILES,
    resolve_identity,
)
from .names import allocate_name, resolve_name

__all__ = [
    "BindingManager",
    "ClaudeActorConfig",
    "ClaudeCapability",
    "CLAUDE_ACTOR_PROFILES",
    "resolve_identity",
    "allocate_name",
    "resolve_name",
]
