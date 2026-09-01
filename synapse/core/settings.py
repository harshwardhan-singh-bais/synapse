"""
Settings configuration — loads settings.toml for TUI preferences.

Ported from thurbox's agent/settings_config.rs.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .paths import CONFIG_DIR


@dataclass
class FeatureFlags:
    """Feature flags for enabling/disabling Synapse features."""
    tasks: bool = True
    automations: bool = True
    global_search: bool = True
    shell_pane: bool = True
    mouse: bool = True
    notifications: bool = True
    soft_delete: bool = True
    version_check: bool = True
    auto_update: bool = True
    perf_hud: bool = False


@dataclass
class NotificationSettings:
    """Notification preferences."""
    also_on_waiting: bool = False
    suppress_for_active: bool = True
    sound: bool = False
    min_interval_secs: int = 60
    backend: str = "auto"  # auto | dbus | windows | off


@dataclass
class ClipboardSettings:
    """Clipboard preferences."""
    provider: str = "auto"  # auto | native | osc52 | none


@dataclass
class Settings:
    """Synapse settings from settings.toml."""
    config_version: int = 1
    scrollback_lines: int = 10000
    two_panel_min_cols: int = 80
    three_panel_min_cols: int = 120
    audit_retention_days: int = 30
    features: FeatureFlags = field(default_factory=FeatureFlags)
    notifications: NotificationSettings = field(default_factory=NotificationSettings)
    clipboard: ClipboardSettings = field(default_factory=ClipboardSettings)


def settings_path() -> Path:
    """Return the path to settings.toml."""
    return CONFIG_DIR / "settings.toml"


def load_settings() -> Settings:
    """Load settings from settings.toml, falling back to defaults."""
    path = settings_path()
    if not path.exists():
        return Settings()

    try:
        with path.open("rb") as fh:
            raw = tomllib.load(fh)
    except Exception:
        return Settings()

    settings = Settings()
    settings.config_version = raw.get("config_version", 1)
    settings.scrollback_lines = raw.get("scrollback_lines", 10000)
    settings.two_panel_min_cols = raw.get("two_panel_min_cols", 80)
    settings.three_panel_min_cols = raw.get("three_panel_min_cols", 120)
    settings.audit_retention_days = raw.get("audit_retention_days", 30)

    # Feature flags
    feat = raw.get("features", {})
    if isinstance(feat, dict):
        for key in ["tasks", "automations", "global_search", "shell_pane",
                     "mouse", "notifications", "soft_delete", "version_check",
                     "auto_update", "perf_hud"]:
            if key in feat:
                setattr(settings.features, key, bool(feat[key]))

    # Notification settings
    notif = raw.get("notifications", {})
    if isinstance(notif, dict):
        for key in ["also_on_waiting", "suppress_for_active", "sound",
                     "min_interval_secs", "backend"]:
            if key in notif:
                setattr(settings.notifications, key, notif[key])

    # Clipboard settings
    clip = raw.get("clipboard", {})
    if isinstance(clip, dict):
        if "provider" in clip:
            settings.clipboard.provider = clip["provider"]

    return settings


def seed_settings() -> None:
    """Write default settings.toml if it doesn't exist."""
    path = settings_path()
    if path.exists():
        return

    default_content = """\
config_version = 1
scrollback_lines = 10000
two_panel_min_cols = 80
three_panel_min_cols = 120
audit_retention_days = 30

[features]
tasks = true
automations = true
global_search = true
shell_pane = true
mouse = true
notifications = true
soft_delete = true
version_check = true
auto_update = true
perf_hud = false

[notifications]
also_on_waiting = false
suppress_for_active = true
sound = false
min_interval_secs = 60
backend = "auto"

[clipboard]
provider = "auto"
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(default_content, encoding="utf-8")
