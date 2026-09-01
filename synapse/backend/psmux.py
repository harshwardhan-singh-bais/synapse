"""
psmux (Pseudo-Multiplexer) backend for Windows.

This module provides a tmux-like terminal multiplexing experience on Windows
using Windows Console APIs. It's an alternative to tmux on Windows where
tmux is not natively available.

psmux uses Windows ConPTY for terminal emulation and provides:
- Session management (create, attach, detach, kill)
- Window management (create, switch, close)
- Pane management (split, resize)
- Command execution in isolated terminals

Note: This is the Windows equivalent of the tmux backend in tmux.py.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import os
import sys
import threading
import time
from dataclasses import dataclass
from typing import Optional

from ..pty.windows import WindowsPtyProxy, WindowsPtyConfig, HAS_CONPTY, IS_WINDOWS

log = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Session / Window / Pane data classes
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class PsmuxPane:
    """Represents a single pane in psmux."""
    pane_id: str
    window_id: str
    session_name: str
    proxy: Optional[WindowsPtyProxy] = None
    cwd: str = ""
    command: str = ""
    title: str = ""


@dataclass
class PsmuxWindow:
    """Represents a window in psmux."""
    window_id: str
    session_name: str
    name: str = ""
    panes: list[PsmuxPane] = None

    def __post_init__(self):
        if self.panes is None:
            self.panes = []


@dataclass
class PsmuxSession:
    """Represents a psmux session."""
    name: str
    windows: dict[str, PsmuxWindow] = None
    created_at: float = 0.0

    def __post_init__(self):
        if self.windows is None:
            self.windows = {}
        if self.created_at == 0.0:
            self.created_at = time.time()


# ──────────────────────────────────────────────────────────────────────────────
# psmux Backend
# ──────────────────────────────────────────────────────────────────────────────


class PsmuxBackend:
    """
    psmux backend for Windows.

    Provides tmux-like terminal multiplexing using Windows ConPTY.
    """

    def __init__(self) -> None:
        if not IS_WINDOWS:
            raise RuntimeError("PsmuxBackend is only available on Windows")

        self._sessions: dict[str, PsmuxSession] = {}
        self._active_session: Optional[str] = None
        self._lock = threading.Lock()
        self._id_counter = 0

    def _next_id(self) -> str:
        """Generate a unique ID."""
        self._id_counter += 1
        return f"psmux-{self._id_counter}"

    def _generate_pane_id(self) -> str:
        """Generate a pane ID."""
        return f"%{self._id_counter}"

    def _generate_window_id(self) -> str:
        """Generate a window ID."""
        return f"@{self._id_counter}"

    # ──────────────────────────────────────────────────────────────────────────
    # Session lifecycle
    # ──────────────────────────────────────────────────────────────────────────

    def new_session(
        self,
        session_name: str,
        window_name: str = "main",
        cwd: Optional[str] = None,
    ) -> PsmuxSession:
        """Create a new psmux session."""
        with self._lock:
            if session_name in self._sessions:
                raise ValueError(f"Session '{session_name}' already exists")

            session = PsmuxSession(name=session_name)

            # Create the first window
            window_id = self._generate_window_id()
            window = PsmuxWindow(
                window_id=window_id,
                session_name=session_name,
                name=window_name,
            )
            session.windows[window_id] = window

            self._sessions[session_name] = session
            self._active_session = session_name

            log.info("Created psmux session: %s", session_name)
            return session

    def kill_session(self, session_name: str) -> None:
        """Kill a psmux session and all its panes."""
        with self._lock:
            session = self._sessions.get(session_name)
            if not session:
                return

            # Kill all panes
            for window in session.windows.values():
                for pane in window.panes:
                    if pane.proxy:
                        pane.proxy.cleanup()

            del self._sessions[session_name]

            if self._active_session == session_name:
                self._active_session = None

            log.info("Killed psmux session: %s", session_name)

    def list_sessions(self) -> list[str]:
        """List all active sessions."""
        with self._lock:
            return list(self._sessions.keys())

    def has_session(self, session_name: str) -> bool:
        """Check if a session exists."""
        with self._lock:
            return session_name in self._sessions

    # ──────────────────────────────────────────────────────────────────────────
    # Window management
    # ──────────────────────────────────────────────────────────────────────────

    def new_window(
        self,
        session_name: str,
        window_name: str = "",
        cwd: Optional[str] = None,
    ) -> PsmuxWindow:
        """Create a new window in a session."""
        with self._lock:
            session = self._sessions.get(session_name)
            if not session:
                raise ValueError(f"Session '{session_name}' not found")

            window_id = self._generate_window_id()
            window = PsmuxWindow(
                window_id=window_id,
                session_name=session_name,
                name=window_name or f"window-{len(session.windows) + 1}",
            )
            session.windows[window_id] = window
            log.info("Created window %s in session %s", window_id, session_name)
            return window

    def kill_window(self, session_name: str, window_id: str) -> None:
        """Kill a window and its panes."""
        with self._lock:
            session = self._sessions.get(session_name)
            if not session:
                return

            window = session.windows.get(window_id)
            if not window:
                return

            # Kill all panes in the window
            for pane in window.panes:
                if pane.proxy:
                    pane.proxy.cleanup()

            del session.windows[window_id]
            log.info("Killed window %s in session %s", window_id, session_name)

    # ──────────────────────────────────────────────────────────────────────────
    # Pane management
    # ──────────────────────────────────────────────────────────────────────────

    def new_pane(
        self,
        session_name: str,
        window_id: str,
        command: str,
        args: list[str] = None,
        cwd: Optional[str] = None,
    ) -> PsmuxPane:
        """Create a new pane in a window."""
        with self._lock:
            session = self._sessions.get(session_name)
            if not session:
                raise ValueError(f"Session '{session_name}' not found")

            window = session.windows.get(window_id)
            if not window:
                raise ValueError(f"Window '{window_id}' not found")

            pane_id = self._generate_pane_id()
            pane_cwd = cwd or os.getcwd()

            # Create the PTY proxy
            config = WindowsPtyConfig(
                cols=220,
                rows=50,
            )

            proxy = WindowsPtyProxy(
                command=command,
                args=args or [],
                config=config,
                cwd=pane_cwd,
            )

            pane = PsmuxPane(
                pane_id=pane_id,
                window_id=window_id,
                session_name=session_name,
                proxy=proxy,
                cwd=pane_cwd,
                command=command,
            )

            window.panes.append(pane)

            # Spawn the process
            if proxy.spawn():
                log.info(
                    "Created pane %s in window %s (session %s)",
                    pane_id,
                    window_id,
                    session_name,
                )
            else:
                log.error("Failed to spawn process in pane %s", pane_id)

            return pane

    def send_text(self, pane_id: str, text: str, press_enter: bool = True) -> None:
        """Send text to a pane."""
        with self._lock:
            pane = self._find_pane(pane_id)
            if not pane or not pane.proxy:
                return

            pane.proxy.write_text(text)
            if press_enter:
                pane.proxy.send_enter()

    def send_key(self, pane_id: str, key: str) -> None:
        """Send a key sequence to a pane."""
        # Convert key names to bytes
        key_map = {
            "Enter": b"\r",
            "Escape": b"\x1b",
            "Tab": b"\t",
            "Backspace": b"\x08",
            "C-c": b"\x03",
            "C-d": b"\x04",
        }

        key_bytes = key_map.get(key, key.encode("utf-8"))
        with self._lock:
            pane = self._find_pane(pane_id)
            if pane and pane.proxy:
                pane.proxy.write(key_bytes)

    def capture(self, pane_id: str, lines: int = 100) -> str:
        """Capture output from a pane."""
        # Note: This is a simplified implementation
        # A full implementation would buffer output and extract the last N lines
        with self._lock:
            pane = self._find_pane(pane_id)
            if not pane or not pane.proxy:
                return ""
            # In a real implementation, we'd read from a buffer
            return f"[psmux capture: pane {pane_id}]"

    def resize_pane(
        self,
        pane_id: str,
        width: Optional[int] = None,
        height: Optional[int] = None,
    ) -> None:
        """Resize a pane."""
        with self._lock:
            pane = self._find_pane(pane_id)
            if not pane or not pane.proxy:
                return

            # Get current size if not specified
            if width is None or height is None:
                # Default to current size
                width = width or 220
                height = height or 50

            pane.proxy.resize(width, height)

    def kill_pane(self, pane_id: str) -> None:
        """Kill a pane."""
        with self._lock:
            pane = self._find_pane(pane_id)
            if not pane:
                return

            if pane.proxy:
                pane.proxy.cleanup()

            # Remove from window
            session = self._sessions.get(pane.session_name)
            if session:
                window = session.windows.get(pane.window_id)
                if window:
                    window.panes = [p for p in window.panes if p.pane_id != pane_id]

    def list_panes(self) -> list[PsmuxPane]:
        """List all panes across all sessions."""
        with self._lock:
            panes = []
            for session in self._sessions.values():
                for window in session.windows.values():
                    panes.extend(window.panes)
            return panes

    def pane_exists(self, pane_id: str) -> bool:
        """Check if a pane exists."""
        with self._lock:
            return self._find_pane(pane_id) is not None

    def _find_pane(self, pane_id: str) -> Optional[PsmuxPane]:
        """Find a pane by ID (must be called with lock held)."""
        for session in self._sessions.values():
            for window in session.windows.values():
                for pane in window.panes:
                    if pane.pane_id == pane_id:
                        return pane
        return None

    # ──────────────────────────────────────────────────────────────────────────
    # Attach / detach
    # ──────────────────────────────────────────────────────────────────────────

    def attach(self, pane_id: str) -> None:
        """Attach the current terminal to a pane.

        This is a simplified implementation that shows the pane's output.
        A full implementation would take over the terminal.
        """
        with self._lock:
            pane = self._find_pane(pane_id)
            if not pane or not pane.proxy:
                return

            # In a real implementation, we'd redirect I/O
            # For now, just print a message
            print(f"Attached to pane {pane_id} (session: {pane.session_name})")
            print("Press Ctrl+C to detach")

            try:
                # Wait for the process to finish
                while pane.proxy.is_alive():
                    time.sleep(0.1)
            except KeyboardInterrupt:
                print(f"\nDetached from pane {pane_id}")

    # ──────────────────────────────────────────────────────────────────────────
    # Status
    # ──────────────────────────────────────────────────────────────────────────

    def status(self) -> dict:
        """Get psmux status."""
        with self._lock:
            total_sessions = len(self._sessions)
            total_windows = sum(len(s.windows) for s in self._sessions.values())
            total_panes = sum(
                len(w.panes)
                for s in self._sessions.values()
                for w in s.windows.values()
            )

            return {
                "sessions": total_sessions,
                "windows": total_windows,
                "panes": total_panes,
                "active_session": self._active_session,
            }

    def ensure_server(self) -> None:
        """Ensure the psmux server is running.

        For psmux, this is a no-op since we manage state in-memory.
        """
        pass
