"""Synapse configuration — TOML-backed with SYNAPSE_* env-var overrides."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Optional

import tomli_w
from pydantic import BaseModel, ConfigDict, Field

from .paths import CONFIG_DIR, DATA_DIR


# ──────────────────────────────────────────────────────────────────────────────
# Agent definitions  (agents.toml)
# ──────────────────────────────────────────────────────────────────────────────


class AgentDef(BaseModel):
    """Definition for a single agent entry in ``agents.toml``."""

    model_config = ConfigDict(extra="allow")

    name: str
    command: Optional[str] = None           # shell command that starts the agent
    env: dict[str, str] = Field(default_factory=dict)
    model: Optional[str] = None             # e.g. "claude-opus-4-5"
    backend_type: str = "local-tmux"        # 'local-tmux' | 'ssh:<name>' | 'wsl:<name>'
    notes: Optional[str] = None
    system_prompt: Optional[str] = None     # per-agent system prompt override
    launch_args: list[str] = Field(default_factory=list)  # extra CLI args for launch
    fork_args: list[str] = Field(default_factory=list)     # args for forking/resuming
    resume_args: list[str] = Field(default_factory=list)   # args for resuming sessions


# ──────────────────────────────────────────────────────────────────────────────
# Settings definitions  (settings.toml)
# ──────────────────────────────────────────────────────────────────────────────


class SettingsDef(BaseModel):
    """Runtime settings loaded from ``~/.config/synapse/settings.toml``."""

    model_config = ConfigDict(extra="allow")

    # General
    log_level: str = Field(default="INFO")
    theme: str = Field(default="dark-neon")
    language: str = Field(default="en")

    # Agent defaults
    default_timeout: int = Field(default=1800)          # seconds
    max_retries: int = Field(default=3)
    retry_delay: int = Field(default=5)                 # seconds

    # TUI
    refresh_rate: int = Field(default=2)                # seconds
    max_sidebar_items: int = Field(default=50)

    # Relay
    relay_keepalive: int = Field(default=60)            # seconds
    relay_reconnect_delay: int = Field(default=10)      # seconds
    relay_max_reconnect: int = Field(default=10)

    # Hooks
    hook_timeout: int = Field(default=30)               # seconds
    hook_max_retries: int = Field(default=2)

    # Paths
    transcript_dir: Optional[str] = Field(default=None)
    archive_dir: Optional[str] = Field(default=None)

    # Plugin system
    plugins_enabled: bool = Field(default=True)
    plugin_paths: list[str] = Field(default_factory=list)

    @classmethod
    def load(cls) -> "SettingsDef":
        """Load settings from ``~/.config/synapse/settings.toml``."""
        settings_path = CONFIG_DIR / "settings.toml"
        if not settings_path.exists():
            return cls()
        with settings_path.open("rb") as fh:
            data: dict = tomllib.load(fh)
        return cls.model_validate(data)

    def save(self) -> None:
        """Persist settings to ``~/.config/synapse/settings.toml``."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        settings_path = CONFIG_DIR / "settings.toml"
        with settings_path.open("wb") as fh:
            tomli_w.dump(self.model_dump(), fh)


def load_agents_toml() -> dict[str, AgentDef]:
    """Parse ``~/.config/synapse/agents.toml`` and return a name → AgentDef map.

    Supports two TOML layouts:
    1. ``[[agents]]`` array-of-tables (thurbox format):
       ````toml
       [[agents]]\n       name = "claude"\n       command = "claude"
       ````
    2. ``[agents.<name>]`` nested-dict format:
       ````toml
       [agents.claude]\n       command = "claude"
       ````

    Returns an empty dict if the file does not exist yet.
    """
    agents_path = CONFIG_DIR / "agents.toml"
    if not agents_path.exists():
        return {}

    with agents_path.open("rb") as fh:
        raw: dict = tomllib.load(fh)

    result: dict[str, AgentDef] = {}

    # Layout 1: [[agents]] array-of-tables
    if "agents" in raw and isinstance(raw["agents"], list):
        for entry in raw["agents"]:
            if isinstance(entry, dict) and "name" in entry:
                name = entry["name"]
                # Remove 'name' from entry to avoid duplicate keyword argument
                entry_data = {k: v for k, v in entry.items() if k != "name"}
                result[name] = AgentDef(name=name, **entry_data)
        return result

    # Layout 2: {name: {config...}} mapping
    for name, body in raw.items():
        if isinstance(body, dict) and name not in ("synapse", "features", "relay"):
            result[name] = AgentDef(name=name, **body)

    return result


# ──────────────────────────────────────────────────────────────────────────────
# Main configuration
# ──────────────────────────────────────────────────────────────────────────────

_DEFAULT_DB_PATH = DATA_DIR / "synapse.db"
_CONFIG_FILE = CONFIG_DIR / "config.toml"


class SynapseConfig(BaseModel):
    """Runtime configuration for Synapse.

    Values are sourced in ascending priority order:
    1. Hard-coded defaults (field defaults below).
    2. ``~/.config/synapse/config.toml``.
    3. ``SYNAPSE_*`` environment variables (highest priority).
    """

    model_config = ConfigDict(extra="ignore")

    db_path: Path = Field(default=_DEFAULT_DB_PATH)
    default_agent: str = Field(default="claude")
    effort: str = Field(default="standard")         # 'low' | 'standard' | 'high' | 'max'
    terminal: str = Field(default="tmux")
    relay_url: Optional[str] = Field(default=None)
    relay_enabled: bool = Field(default=False)
    max_parallel: int = Field(default=2)
    audit_retention_days: int = Field(default=30)
    auto_approve: bool = Field(default=True)          # auto-approve agent actions
    auto_subscribe: str = Field(default="collision")  # comma-separated subscription presets
    auto_trust_workspace: bool = Field(default=False)  # auto-trust workspace on first use
    title_mode: str = Field(default="combined")       # 'combined' | 'label' | 'off'

    # ── factory ──────────────────────────────────────────────────

    @classmethod
    def load(cls) -> "SynapseConfig":
        """Load config from TOML file then apply env-var overrides."""
        data: dict = {}

        if _CONFIG_FILE.exists():
            with _CONFIG_FILE.open("rb") as fh:
                data = tomllib.load(fh)

        # Env-var overrides: SYNAPSE_<UPPER_FIELD_NAME>
        env_map = {
            "SYNAPSE_DB_PATH": ("db_path", Path),
            "SYNAPSE_DEFAULT_AGENT": ("default_agent", str),
            "SYNAPSE_EFFORT": ("effort", str),
            "SYNAPSE_TERMINAL": ("terminal", str),
            "SYNAPSE_RELAY_URL": ("relay_url", str),
            "SYNAPSE_RELAY_ENABLED": ("relay_enabled", _parse_bool),
            "SYNAPSE_MAX_PARALLEL": ("max_parallel", int),
            "SYNAPSE_AUDIT_RETENTION_DAYS": ("audit_retention_days", int),
            "SYNAPSE_AUTO_APPROVE": ("auto_approve", _parse_bool),
            "SYNAPSE_AUTO_SUBSCRIBE": ("auto_subscribe", str),
            "SYNAPSE_AUTO_TRUST_WORKSPACE": ("auto_trust_workspace", _parse_bool),
            "SYNAPSE_TITLE_MODE": ("title_mode", str),
        }

        for env_key, (field_name, coerce) in env_map.items():
            raw = os.environ.get(env_key)
            if raw is not None:
                data[field_name] = coerce(raw)

        return cls.model_validate(data)

    # ── validation ──────────────────────────────────────────────

    def validate(self) -> list[str]:
        """Validate the configuration and return a list of warning/error messages.

        Returns an empty list if all settings are valid.
        """
        issues: list[str] = []

        # Validate effort level
        if self.effort not in ("low", "standard", "high", "max"):
            issues.append(f"Invalid effort level: '{self.effort}'. Must be low/standard/high/max.")

        # Validate terminal preset
        valid_terminals = ("tmux", "kitty", "wezterm", "iterm", "alacritty", "ghostty")
        if self.terminal not in valid_terminals:
            issues.append(f"Invalid terminal: '{self.terminal}'. Must be one of: {', '.join(valid_terminals)}.")

        # Validate title mode
        if self.title_mode not in ("combined", "label", "off"):
            issues.append(f"Invalid title_mode: '{self.title_mode}'. Must be combined/label/off.")

        # Validate max_parallel
        if self.max_parallel < 1:
            issues.append(f"max_parallel must be >= 1, got {self.max_parallel}.")

        # Validate audit_retention_days
        if self.audit_retention_days < 1:
            issues.append(f"audit_retention_days must be >= 1, got {self.audit_retention_days}.")

        # Validate relay URL format
        if self.relay_url:
            if not self.relay_url.startswith(("mqtt://", "mqtts://")) and ":" not in self.relay_url:
                issues.append(f"relay_url looks invalid: '{self.relay_url}'. Expected mqtt://host:port.")

        # Validate db_path parent exists
        if not self.db_path.parent.exists():
            issues.append(f"DB parent directory does not exist: {self.db_path.parent}")

        return issues

    def validate_agents(self) -> list[str]:
        """Validate agents.toml and return a list of issues."""
        issues: list[str] = []
        agents = load_agents_toml()
        if not agents:
            issues.append("No agents defined in agents.toml.")
            return issues

        import shutil
        for name, agent_def in agents.items():
            if agent_def.command:
                # Check if the command binary exists
                binary = agent_def.command.split()[0]
                if not shutil.which(binary):
                    issues.append(f"Agent '{name}': command binary '{binary}' not found in PATH.")
            if agent_def.backend_type not in ("local-tmux",):
                if not agent_def.backend_type.startswith(("ssh:", "wsl:")):
                    issues.append(f"Agent '{name}': unknown backend_type '{agent_def.backend_type}'.")

        return issues

    # ── persistence ──────────────────────────────────────────────

    def save(self) -> None:
        """Persist current config values to ``~/.config/synapse/config.toml``."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)

        serialisable = {
            "db_path": str(self.db_path),
            "default_agent": self.default_agent,
            "effort": self.effort,
            "terminal": self.terminal,
            "relay_enabled": self.relay_enabled,
            "max_parallel": self.max_parallel,
            "audit_retention_days": self.audit_retention_days,
            "auto_approve": self.auto_approve,
            "auto_subscribe": self.auto_subscribe,
            "auto_trust_workspace": self.auto_trust_workspace,
            "title_mode": self.title_mode,
        }
        if self.relay_url is not None:
            serialisable["relay_url"] = self.relay_url

        with _CONFIG_FILE.open("wb") as fh:
            tomli_w.dump(serialisable, fh)


# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────────


def _parse_bool(value: str) -> bool:
    """Interpret common truthy/falsy strings from environment variables."""
    return value.strip().lower() in {"1", "true", "yes", "on"}
