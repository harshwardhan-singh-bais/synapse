"""
Lua plugin system for the Synapse TUI.

Provides:
- Plugin loading and unloading
- Hot-reload via file watcher
- Capability-based sandboxing
- Plugin API for custom panels and widgets

Requires lupa (Lua runtime) as an optional dependency.
"""
from __future__ import annotations

import hashlib
import importlib
import logging
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional

log = logging.getLogger(__name__)

# Try to import lupa for Lua runtime
try:
    from lupa import LuaRuntime  # type: ignore[import]
    HAS_LUA = True
except ImportError:
    HAS_LUA = False


# ──────────────────────────────────────────────────────────────────────────────
# Plugin capabilities (sandboxing)
# ──────────────────────────────────────────────────────────────────────────────


class PluginCapability(str, Enum):
    """Capabilities that a plugin can request."""
    READ_SESSIONS = "read_sessions"
    WRITE_SESSIONS = "write_sessions"
    READ_MESSAGES = "read_messages"
    WRITE_MESSAGES = "write_messages"
    READ_CONFIG = "read_config"
    WRITE_CONFIG = "write_config"
    ADD_WIDGET = "add_widget"
    ADD_KEYBINDING = "add_keybinding"
    FILESYSTEM_READ = "filesystem_read"
    FILESYSTEM_WRITE = "filesystem_write"
    NETWORK = "network"
    SUBPROCESS = "subprocess"


# Default capabilities for plugins (sandboxed by default)
DEFAULT_CAPABILITIES = frozenset({
    PluginCapability.READ_SESSIONS,
    PluginCapability.READ_MESSAGES,
    PluginCapability.READ_CONFIG,
    PluginCapability.ADD_WIDGET,
    PluginCapability.ADD_KEYBINDING,
})

# Dangerous capabilities that require explicit approval
DANGEROUS_CAPABILITIES = frozenset({
    PluginCapability.WRITE_SESSIONS,
    PluginCapability.WRITE_MESSAGES,
    PluginCapability.WRITE_CONFIG,
    PluginCapability.FILESYSTEM_WRITE,
    PluginCapability.NETWORK,
    PluginCapability.SUBPROCESS,
})


# ──────────────────────────────────────────────────────────────────────────────
# Plugin metadata
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class PluginMeta:
    """Metadata for a loaded plugin."""
    name: str
    version: str = "0.1.0"
    description: str = ""
    author: str = ""
    capabilities: list[PluginCapability] = field(default_factory=list)
    entry_point: str = "plugin"  # Lua function name to call on load


@dataclass
class PluginState:
    """State of a loaded plugin."""
    path: Path
    meta: Optional[PluginMeta] = None
    loaded: bool = False
    error: Optional[str] = None
    last_modified: float = 0.0
    checksum: str = ""


# ──────────────────────────────────────────────────────────────────────────────
# Plugin sandbox
# ──────────────────────────────────────────────────────────────────────────────


class PluginSandbox:
    """Sandboxed Lua runtime for a single plugin."""

    def __init__(
        self,
        plugin_state: PluginState,
        allowed_capabilities: frozenset[PluginCapability],
        api_provider: Optional[Callable[[PluginCapability], Any]] = None,
    ) -> None:
        self.state = plugin_state
        self.allowed_capabilities = allowed_capabilities
        self._api_provider = api_provider
        self._lua: Optional[Any] = None
        self._globals: dict[str, Any] = {}

    def _check_capability(self, cap: PluginCapability) -> bool:
        """Check if the plugin has a specific capability."""
        if cap not in self.allowed_capabilities:
            log.warning(
                "Plugin %s denied capability: %s",
                self.state.meta.name if self.state.meta else "unknown",
                cap.value,
            )
            return False
        return True

    def _build_safe_api(self) -> dict[str, Any]:
        """Build a sandboxed API for the plugin."""
        api: dict[str, Any] = {}

        # Read-only session access
        if self._check_capability(PluginCapability.READ_SESSIONS):
            api["get_sessions"] = self._make_api_wrapper(PluginCapability.READ_SESSIONS)

        # Read-only message access
        if self._check_capability(PluginCapability.READ_MESSAGES):
            api["get_messages"] = self._make_api_wrapper(PluginCapability.READ_MESSAGES)

        # Widget registration
        if self._check_capability(PluginCapability.ADD_WIDGET):
            api["register_widget"] = self._make_api_wrapper(PluginCapability.ADD_WIDGET)

        # Keybinding registration
        if self._check_capability(PluginCapability.ADD_KEYBINDING):
            api["register_keybinding"] = self._make_api_wrapper(PluginCapability.ADD_KEYBINDING)

        return api

    def _make_api_wrapper(self, cap: PluginCapability) -> Callable[..., Any]:
        """Create a wrapper function that checks capabilities."""
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not self._check_capability(cap):
                raise PermissionError(f"Plugin lacks capability: {cap.value}")
            if self._api_provider:
                return self._api_provider(cap)(*args, **kwargs)
            return None
        return wrapper

    def load(self) -> bool:
        """Load and initialize the plugin."""
        if not HAS_LUA:
            self.state.error = "Lua runtime (lupa) not installed"
            return False

        try:
            self._lua = LuaRuntime(unpack_returned_tuples=True)
            self._globals = self._build_safe_api()

            # Read the plugin file
            content = self.state.path.read_text(encoding="utf-8")

            # Execute the plugin code
            self._lua.execute(content)

            # Call the entry point
            entry_fn = self._lua.eval(self.state.meta.entry_point if self.state.meta else "plugin")
            if entry_fn:
                entry_fn(self._globals)

            self.state.loaded = True
            self.state.error = None
            log.info("Loaded plugin: %s", self.state.path.name)
            return True

        except Exception as exc:
            self.state.error = str(exc)
            self.state.loaded = False
            log.error("Failed to load plugin %s: %s", self.state.path.name, exc)
            return False

    def unload(self) -> None:
        """Unload the plugin."""
        self._lua = None
        self._globals.clear()
        self.state.loaded = False
        log.info("Unloaded plugin: %s", self.state.path.name)


# ──────────────────────────────────────────────────────────────────────────────
# Plugin manager
# ──────────────────────────────────────────────────────────────────────────────


class PluginManager:
    """Manages loading, unloading, and hot-reloading of Lua plugins."""

    def __init__(
        self,
        plugin_dir: Optional[Path] = None,
        allowed_capabilities: Optional[frozenset[PluginCapability]] = None,
    ) -> None:
        self.plugin_dir = plugin_dir or Path.home() / ".config" / "synapse" / "plugins"
        self.allowed_capabilities = allowed_capabilities or DEFAULT_CAPABILITIES
        self._plugins: dict[str, PluginState] = {}
        self._sandboxes: dict[str, PluginSandbox] = {}
        self._watcher_thread: Optional[threading.Thread] = None
        self._watching = False
        self._callbacks: list[Callable[[str, str], None]] = []  # (event, plugin_name)

    def discover_plugins(self) -> list[Path]:
        """Discover all .lua files in the plugin directory."""
        if not self.plugin_dir.exists():
            return []

        plugins = []
        for path in self.plugin_dir.glob("*.lua"):
            if path.is_file():
                plugins.append(path)
        return plugins

    def load_plugin(self, path: Path) -> bool:
        """Load a single plugin from a .lua file."""
        plugin_name = path.stem

        # Check if already loaded
        if plugin_name in self._plugins:
            existing = self._plugins[plugin_name]
            if existing.loaded:
                return True

        # Calculate checksum for change detection
        try:
            content = path.read_bytes()
            checksum = hashlib.sha256(content).hexdigest()
        except OSError as exc:
            log.error("Cannot read plugin %s: %s", path, exc)
            return False

        # Parse metadata from the file
        meta = self._parse_plugin_meta(content.decode("utf-8", errors="replace"))

        state = PluginState(
            path=path,
            meta=meta,
            last_modified=path.stat().st_mtime,
            checksum=checksum,
        )

        # Check if capabilities are allowed
        if meta and meta.capabilities:
            denied = set(meta.capabilities) - self.allowed_capabilities
            if denied:
                denied_str = ", ".join(c.value for c in denied)
                log.warning(
                    "Plugin %s requests denied capabilities: %s",
                    plugin_name,
                    denied_str,
                )
                # Filter to only allowed capabilities
                meta.capabilities = [c for c in meta.capabilities if c in self.allowed_capabilities]

        sandbox = PluginSandbox(
            plugin_state=state,
            allowed_capabilities=self.allowed_capabilities,
        )

        if sandbox.load():
            self._plugins[plugin_name] = state
            self._sandboxes[plugin_name] = sandbox
            self._emit_event("loaded", plugin_name)
            return True
        else:
            self._plugins[plugin_name] = state
            return False

    def load_all(self) -> int:
        """Load all discovered plugins. Returns the number of successfully loaded plugins."""
        count = 0
        for path in self.discover_plugins():
            if self.load_plugin(path):
                count += 1
        return count

    def unload_plugin(self, name: str) -> None:
        """Unload a plugin by name."""
        if name in self._sandboxes:
            self._sandboxes[name].unload()
            del self._sandboxes[name]
        if name in self._plugins:
            self._plugins[name].loaded = False
            self._emit_event("unloaded", name)

    def reload_plugin(self, name: str) -> bool:
        """Reload a plugin (unload + load)."""
        self.unload_plugin(name)
        if name in self._plugins:
            return self.load_plugin(self._plugins[name].path)
        return False

    def get_plugin(self, name: str) -> Optional[PluginState]:
        """Get plugin state by name."""
        return self._plugins.get(name)

    def list_plugins(self) -> list[PluginState]:
        """List all discovered plugins."""
        return list(self._plugins.values())

    def on_event(self, callback: Callable[[str, str], None]) -> None:
        """Register a callback for plugin events."""
        self._callbacks.append(callback)

    def _emit_event(self, event: str, plugin_name: str) -> None:
        """Emit a plugin event to all registered callbacks."""
        for cb in self._callbacks:
            try:
                cb(event, plugin_name)
            except Exception as exc:
                log.error("Plugin event callback error: %s", exc)

    # ──────────────────────────────────────────────────────────────────────────
    # Hot-reload
    # ──────────────────────────────────────────────────────────────────────────

    def start_watching(self, interval: float = 2.0) -> None:
        """Start watching for plugin file changes (hot-reload)."""
        if self._watching:
            return

        self._watching = True
        self._watcher_thread = threading.Thread(
            target=self._watch_loop,
            args=(interval,),
            daemon=True,
            name="plugin-watcher",
        )
        self._watcher_thread.start()
        log.info("Plugin file watcher started (interval: %.1fs)", interval)

    def stop_watching(self) -> None:
        """Stop watching for plugin file changes."""
        self._watching = False
        if self._watcher_thread:
            self._watcher_thread.join(timeout=5.0)
            self._watcher_thread = None

    def _watch_loop(self, interval: float) -> None:
        """Background loop that checks for plugin file modifications."""
        while self._watching:
            time.sleep(interval)
            self._check_for_changes()

    def _check_for_changes(self) -> None:
        """Check if any plugin files have been modified."""
        for path in self.discover_plugins():
            plugin_name = path.stem
            try:
                stat = path.stat()
                current_mtime = stat.st_mtime

                if plugin_name in self._plugins:
                    state = self._plugins[plugin_name]
                    if current_mtime > state.last_modified:
                        # File changed — reload
                        log.info(
                            "Plugin file changed, reloading: %s",
                            path.name,
                        )
                        self.reload_plugin(plugin_name)
                else:
                    # New plugin — load it
                    log.info("New plugin detected, loading: %s", path.name)
                    self.load_plugin(path)

            except OSError:
                continue

    # ──────────────────────────────────────────────────────────────────────────
    # Metadata parsing
    # ──────────────────────────────────────────────────────────────────────────

    def _parse_plugin_meta(self, content: str) -> Optional[PluginMeta]:
        """Parse plugin metadata from Lua comments.

        Expects metadata in a comment block at the top of the file:
        -- @name PluginName
        -- @version 1.0.0
        -- @description A cool plugin
        -- @author John Doe
        -- @capability read_sessions
        -- @capability add_widget
        -- @entry my_plugin_init
        """
        name = None
        version = "0.1.0"
        description = ""
        author = ""
        capabilities = []
        entry_point = "plugin"

        for line in content.splitlines():
            line = line.strip()
            if not line.startswith("-- @"):
                if name is not None:
                    break  # Stop parsing after first non-metadata line
                continue

            if line.startswith("-- @name "):
                name = line[9:].strip()
            elif line.startswith("-- @version "):
                version = line[12:].strip()
            elif line.startswith("-- @description "):
                description = line[17:].strip()
            elif line.startswith("-- @author "):
                author = line[11:].strip()
            elif line.startswith("-- @capability "):
                cap_str = line[15:].strip()
                try:
                    capabilities.append(PluginCapability(cap_str))
                except ValueError:
                    log.warning("Unknown plugin capability: %s", cap_str)
            elif line.startswith("-- @entry "):
                entry_point = line[10:].strip()

        if name:
            return PluginMeta(
                name=name,
                version=version,
                description=description,
                author=author,
                capabilities=capabilities,
                entry_point=entry_point,
            )
        return None
