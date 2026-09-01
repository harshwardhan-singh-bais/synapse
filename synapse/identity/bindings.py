"""
Process and session bindings — maps PIDs and session IDs to instance names.

Ported from hcom's instance_binding.rs and identity.rs.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from ..db.database import Database


# ──────────────────────────────────────────────────────────────────────────────
# Claude actor capabilities
# ──────────────────────────────────────────────────────────────────────────────


class ClaudeCapability(str, Enum):
    """Capabilities that a Claude actor can have."""
    # File operations
    READ_FILES = "read_files"
    WRITE_FILES = "write_files"
    EDIT_FILES = "edit_files"
    DELETE_FILES = "delete_files"
    
    # Git operations
    GIT_READ = "git_read"
    GIT_WRITE = "git_write"
    GIT_PUSH = "git_push"
    GIT_DELETE_BRANCH = "git_delete_branch"
    
    # Shell operations
    SHELL_READ = "shell_read"  # read-only commands (ls, cat, grep)
    SHELL_WRITE = "shell_write"  # destructive commands (rm, mv)
    SHELL_INSTALL = "shell_install"  # package installation
    
    # Network operations
    NETWORK_READ = "network_read"  # fetch, curl
    NETWORK_WRITE = "network_write"  # upload, post
    
    # Session operations
    SESSION_CREATE = "session_create"
    SESSION_DELETE = "session_delete"
    SESSION_SEND = "session_send"
    
    # Orchestration
    ORCHESTRATE = "orchestrate"
    VERIFY = "verify"
    
    # Special
    UNRESTRICTED = "unrestricted"  # bypass all checks


@dataclass
class ClaudeActorConfig:
    """Configuration for a Claude actor's capabilities."""
    name: str
    capabilities: list[ClaudeCapability] = field(default_factory=list)
    restrictions: list[str] = field(default_factory=list)  # e.g., ["no-network", "no-git-push"]
    max_file_size_kb: int = 1024  # max file size for writes
    allowed_extensions: list[str] = field(default_factory=list)  # empty = all
    blocked_extensions: list[str] = field(default_factory=lambda: [".env", ".key", ".pem"])
    max_shell_timeout_secs: int = 60
    require_approval: list[str] = field(default_factory=list)  # capabilities requiring approval
    
    def has_capability(self, cap: ClaudeCapability) -> bool:
        """Check if this actor has a specific capability."""
        if ClaudeCapability.UNRESTRICTED in self.capabilities:
            return True
        return cap in self.capabilities
    
    def can_write_file(self, path: str) -> bool:
        """Check if this actor can write to a specific file path."""
        if not self.has_capability(ClaudeCapability.WRITE_FILES):
            return False
        # Check blocked extensions
        for ext in self.blocked_extensions:
            if path.endswith(ext):
                return False
        # Check allowed extensions (empty = all allowed)
        if self.allowed_extensions:
            return any(path.endswith(ext) for ext in self.allowed_extensions)
        return True
    
    def needs_approval(self, cap: ClaudeCapability) -> bool:
        """Check if a capability requires user approval."""
        if ClaudeCapability.UNRESTRICTED in self.capabilities:
            return False
        return cap.value in self.require_approval
    
    def to_dict(self) -> dict:
        """Serialize to dict for JSON storage."""
        return {
            "name": self.name,
            "capabilities": [c.value for c in self.capabilities],
            "restrictions": self.restrictions,
            "max_file_size_kb": self.max_file_size_kb,
            "allowed_extensions": self.allowed_extensions,
            "blocked_extensions": self.blocked_extensions,
            "max_shell_timeout_secs": self.max_shell_timeout_secs,
            "require_approval": self.require_approval,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "ClaudeActorConfig":
        """Deserialize from dict."""
        caps = []
        for c in data.get("capabilities", []):
            try:
                caps.append(ClaudeCapability(c))
            except ValueError:
                pass
        return cls(
            name=data.get("name", "default"),
            capabilities=caps,
            restrictions=data.get("restrictions", []),
            max_file_size_kb=data.get("max_file_size_kb", 1024),
            allowed_extensions=data.get("allowed_extensions", []),
            blocked_extensions=data.get("blocked_extensions", [".env", ".key", ".pem"]),
            max_shell_timeout_secs=data.get("max_shell_timeout_secs", 60),
            require_approval=data.get("require_approval", []),
        )


# Predefined actor profiles
CLAUDE_ACTOR_PROFILES: dict[str, ClaudeActorConfig] = {
    "default": ClaudeActorConfig(
        name="default",
        capabilities=[
            ClaudeCapability.READ_FILES,
            ClaudeCapability.WRITE_FILES,
            ClaudeCapability.EDIT_FILES,
            ClaudeCapability.GIT_READ,
            ClaudeCapability.GIT_WRITE,
            ClaudeCapability.SHELL_READ,
            ClaudeCapability.SESSION_SEND,
        ],
        require_approval=[ClaudeCapability.GIT_PUSH.value, ClaudeCapability.DELETE_FILES.value],
    ),
    "restricted": ClaudeActorConfig(
        name="restricted",
        capabilities=[
            ClaudeCapability.READ_FILES,
            ClaudeCapability.GIT_READ,
            ClaudeCapability.SHELL_READ,
        ],
    ),
    "unrestricted": ClaudeActorConfig(
        name="unrestricted",
        capabilities=[ClaudeCapability.UNRESTRICTED],
    ),
    "orchestrator": ClaudeActorConfig(
        name="orchestrator",
        capabilities=[
            ClaudeCapability.READ_FILES,
            ClaudeCapability.WRITE_FILES,
            ClaudeCapability.EDIT_FILES,
            ClaudeCapability.GIT_READ,
            ClaudeCapability.GIT_WRITE,
            ClaudeCapability.SHELL_READ,
            ClaudeCapability.SESSION_CREATE,
            ClaudeCapability.SESSION_DELETE,
            ClaudeCapability.SESSION_SEND,
            ClaudeCapability.ORCHESTRATE,
            ClaudeCapability.VERIFY,
        ],
        require_approval=[ClaudeCapability.GIT_PUSH.value],
    ),
}


class BindingManager:
    """Manages process_id → instance_name and session_id → instance_name mappings."""

    def __init__(self, db: Database) -> None:
        self.db = db

    # ──────────────────────────────────────────────────────────────────────────
    # Process bindings
    # ──────────────────────────────────────────────────────────────────────────

    def set_process_binding(self, process_id: str, instance_name: str) -> None:
        """Register a process ID → instance name mapping."""
        now = time.time()
        self.db.execute(
            """
            INSERT INTO kv (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (f"process_binding:{process_id}", instance_name),
        )

    def get_process_binding(self, process_id: str) -> Optional[str]:
        """Look up instance name for a process ID."""
        row = self.db.fetchone(
            "SELECT value FROM kv WHERE key = ?",
            (f"process_binding:{process_id}",),
        )
        return row["value"] if row else None

    def remove_process_binding(self, process_id: str) -> None:
        """Remove a process binding."""
        self.db.execute(
            "DELETE FROM kv WHERE key = ?",
            (f"process_binding:{process_id}",),
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Session bindings
    # ──────────────────────────────────────────────────────────────────────────

    def set_session_binding(self, session_id: str, instance_name: str) -> None:
        """Register a session ID → instance name mapping."""
        now = self.db.now_ms()
        self.db.execute(
            """
            INSERT INTO kv (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (f"session_binding:{session_id}", instance_name),
        )

    def get_session_binding(self, session_id: str) -> Optional[str]:
        """Look up instance name for a session ID."""
        row = self.db.fetchone(
            "SELECT value FROM kv WHERE key = ?",
            (f"session_binding:{session_id}",),
        )
        return row["value"] if row else None

    def remove_session_binding(self, session_id: str) -> None:
        """Remove a session binding."""
        self.db.execute(
            "DELETE FROM kv WHERE key = ?",
            (f"session_binding:{session_id}",),
        )

    def resolve_instance_name(
        self,
        process_id: Optional[str] = None,
        session_id: Optional[str] = None,
        env_name: Optional[str] = None,
    ) -> Optional[str]:
        """Resolve instance name through the priority chain:

        1. process_id binding
        2. session_id binding
        3. env_name (SYNAPSE_INSTANCE_NAME / HCOM_INSTANCE_NAME)
        4. sessions table lookup by session_id
        """
        if process_id:
            name = self.get_process_binding(process_id)
            if name:
                return name

        if session_id:
            name = self.get_session_binding(session_id)
            if name:
                return name
            # Try sessions table
            row = self.db.fetchone(
                "SELECT name FROM sessions WHERE id = ? AND deleted_at IS NULL",
                (session_id,),
            )
            if row:
                return row["name"]

        if env_name:
            return env_name

        return None

    # ──────────────────────────────────────────────────────────────────────────
    # Cleanup
    # ──────────────────────────────────────────────────────────────────────────

    def cleanup_stale_bindings(self, max_age_secs: int = 86400) -> int:
        """Remove bindings older than max_age_secs. Returns count removed."""
        # For now, we don't track timestamps on bindings
        # This is a placeholder for future implementation
        return 0


# ──────────────────────────────────────────────────────────────────────────────
# Identity resolver (combines all resolution strategies)
# ──────────────────────────────────────────────────────────────────────────────


def resolve_identity(
    db: Database,
    process_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Optional[str]:
    """High-level identity resolution using all available strategies.

    Priority:
    1. SYNAPSE_PROCESS_ID env → process binding
    2. session_id argument → session binding / sessions table
    3. SYNAPSE_INSTANCE_NAME env
    4. HCOM_INSTANCE_NAME env (compat)
    """
    manager = BindingManager(db)

    # Try process binding
    pid = process_id or os.environ.get("SYNAPSE_PROCESS_ID") or os.environ.get("HCOM_PROCESS_ID")
    if pid:
        name = manager.get_process_binding(pid)
        if name:
            return name

    # Try session binding
    sid = session_id
    if sid:
        name = manager.get_session_binding(sid)
        if name:
            return name
        # Try sessions table
        row = db.fetchone(
            "SELECT name FROM sessions WHERE id = ? AND deleted_at IS NULL",
            (sid,),
        )
        if row:
            return row["name"]

    # Try env vars
    for key in ["SYNAPSE_INSTANCE_NAME", "HCOM_INSTANCE_NAME"]:
        val = os.environ.get(key)
        if val:
            return val

    return None
