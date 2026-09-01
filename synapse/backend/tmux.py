"""
Thin tmux wrapper — all session lifecycle ops go through here.
Uses tmux -L synapse (dedicated server) to avoid interfering with user sessions.
"""
from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)

TMUX_SOCKET = "synapse"


# ──────────────────────────────────────────────────────────────────────────────
# tmux control-mode parser
# ──────────────────────────────────────────────────────────────────────────────


class TmuxControlMode:
    """Parser for tmux control mode output.

    tmux can run in control mode (-C) which outputs structured events.
    This parser handles the output format for monitoring pane state.
    """

    def __init__(self) -> None:
        self._events: list[dict[str, str]] = []
        self._current_event: dict[str, str] = {}
        self._in_event = False

    def parse_line(self, line: str) -> dict[str, str] | None:
        """Parse a single line of control mode output.

        Returns a parsed event dict if a complete event was found, else None.
        """
        line = line.strip()
        if not line:
            return None

        # Lines beginning with % are output lines (not events)
        if line.startswith("%"):
            return None

        # Event start: '%begin ...' or just 'event_name value'
        if line.startswith("%begin"):
            self._in_event = True
            self._current_event = {"type": "begin"}
            return None

        if line.startswith("%end"):
            self._in_event = False
            event = self._current_event.copy()
            self._current_event = {}
            return event if event.get("type") != "begin" else None

        # Key-value pairs within an event
        if " " in line:
            key, _, value = line.partition(" ")
            self._current_event[key] = value
        else:
            self._current_event[line] = ""

        return None

    def parse_all(self, text: str) -> list[dict[str, str]]:
        """Parse multiple lines and return all complete events."""
        events: list[dict[str, str]] = []
        for line in text.splitlines():
            event = self.parse_line(line)
            if event:
                events.append(event)
        return events

    @staticmethod
    def parse_output_line(line: str) -> str | None:
        """Extract the content from a tmux control mode output line.

        Output lines start with '%output ' followed by the pane id and content.
        """
        if line.startswith("%output "):
            parts = line[9:].split(" ", 1)
            if len(parts) == 2:
                return parts[1]
        return None


@dataclass
class TmuxPane:
    pane_id: str       # e.g. "%42"
    window_id: str     # e.g. "@5"
    session_name: str


class TmuxBackend:
    """Manages tmux sessions/windows/panes on a dedicated tmux server socket."""

    def __init__(self, socket: str = TMUX_SOCKET) -> None:
        self.socket = socket

    # ──────────────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────────────

    def _run(self, *args: str) -> str:
        """Run a tmux command against our socket; return stdout (stripped)."""
        cmd = ["tmux", "-L", self.socket] + list(args)
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0 and result.stderr:
                log.debug("tmux stderr: %s", result.stderr.strip())
            return result.stdout.strip()
        except FileNotFoundError:
            log.error("tmux binary not found — is tmux installed?")
            return ""
        except subprocess.TimeoutExpired:
            log.error("tmux command timed out: %s", " ".join(cmd))
            return ""

    def _server_running(self) -> bool:
        """Return True when at least one tmux session exists on our socket."""
        result = subprocess.run(
            ["tmux", "-L", self.socket, "list-sessions"],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0

    # ──────────────────────────────────────────────────────────────
    # Server / session lifecycle
    # ──────────────────────────────────────────────────────────────

    def ensure_server(self) -> None:
        """Start tmux server if not running (creates a detached placeholder session)."""
        if not self._server_running():
            self._run("new-session", "-d", "-s", "synapse-root", "-x", "220", "-y", "50")
            log.debug("Started tmux server on socket '%s'", self.socket)

    def new_window(
        self,
        session_name: str,
        window_name: str,
        cwd: str,
        cmd: str,
    ) -> TmuxPane:
        """Create a new tmux window running *cmd*.

        If the target session doesn't exist, creates it first.
        Returns a :class:`TmuxPane` with the new pane's identifiers.
        """
        self.ensure_server()

        # Check whether the named session exists.
        existing = self._run("list-sessions", "-F", "#{session_name}")
        sessions = existing.splitlines()

        if session_name not in sessions:
            # Create the session with the desired window directly.
            self._run(
                "new-session", "-d",
                "-s", session_name,
                "-n", window_name,
                "-c", cwd,
                "-x", "220", "-y", "50",
            )
            # Start the command in that window's pane.
            self._run("send-keys", "-t", f"{session_name}:{window_name}", cmd, "Enter")
        else:
            # Session exists — open a new window inside it.
            self._run(
                "new-window",
                "-t", session_name,
                "-n", window_name,
                "-c", cwd,
            )
            self._run("send-keys", "-t", f"{session_name}:{window_name}", cmd, "Enter")

        # Retrieve the pane/window IDs for the window we just created.
        fmt = "#{pane_id}:#{window_id}:#{session_name}"
        raw = self._run(
            "list-panes",
            "-t", f"{session_name}:{window_name}",
            "-F", fmt,
        )

        if raw:
            parts = raw.splitlines()[0].split(":")
            if len(parts) >= 3:
                pane_id = parts[0]
                window_id = parts[1]
                sname = ":".join(parts[2:])
                return TmuxPane(pane_id=pane_id, window_id=window_id, session_name=sname)

        # Fallback: construct a best-effort TmuxPane (pane_id unknown until listed).
        log.warning("Could not resolve pane ID for %s:%s; using placeholder", session_name, window_name)
        return TmuxPane(pane_id="", window_id="", session_name=session_name)

    # ──────────────────────────────────────────────────────────────
    # Pane I/O
    # ──────────────────────────────────────────────────────────────

    def send_text(self, pane_id: str, text: str, press_enter: bool = True) -> None:
        """Send *text* to a pane via ``send-keys``.

        The text is sent literally (no shell expansion) then optionally
        followed by an ``Enter`` keystroke.
        """
        # send-keys with -- separates the key list from the literal text.
        self._run("send-keys", "-t", pane_id, text)
        if press_enter:
            self._run("send-keys", "-t", pane_id, "Enter")

    def send_key(self, pane_id: str, key: str) -> None:
        """Send a named key sequence (e.g. ``'Enter'``, ``'C-c'``) to a pane."""
        self._run("send-keys", "-t", pane_id, key)

    def capture(self, pane_id: str, lines: int = 100) -> str:
        """Capture and return the last *lines* lines of visible pane content."""
        # -p prints to stdout; -S -<lines> starts N lines back in scrollback.
        raw = self._run(
            "capture-pane",
            "-p",
            "-t", pane_id,
            "-S", f"-{lines}",
        )
        return raw

    # ──────────────────────────────────────────────────────────────
    # Window / pane management
    # ──────────────────────────────────────────────────────────────

    def kill_window(self, pane_id: str) -> None:
        """Kill the window that contains *pane_id*."""
        try:
            self._run("kill-window", "-t", pane_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("kill_window failed for %s: %s", pane_id, exc)

    def list_panes(self) -> list[TmuxPane]:
        """Return all panes across every window on our tmux socket."""
        if not self._server_running():
            return []

        fmt = "#{pane_id}:#{window_id}:#{session_name}"
        raw = self._run("list-panes", "-a", "-F", fmt)
        panes: list[TmuxPane] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split(":")
            if len(parts) >= 3:
                panes.append(
                    TmuxPane(
                        pane_id=parts[0],
                        window_id=parts[1],
                        session_name=":".join(parts[2:]),
                    )
                )
        return panes

    def pane_exists(self, pane_id: str) -> bool:
        """Return ``True`` if *pane_id* still exists on our socket."""
        existing = {p.pane_id for p in self.list_panes()}
        return pane_id in existing

    def resize_pane(self, pane_id: str, width: Optional[int] = None,
                    height: Optional[int] = None) -> None:
        """Resize a pane to the given *width* and/or *height* (in cells).

        Only the specified dimension is changed; the other stays as-is.
        """
        args: list[str] = ["resize-pane", "-t", pane_id]
        if width is not None:
            args += ["-x", str(width)]
        if height is not None:
            args += ["-y", str(height)]
        if width is not None or height is not None:
            self._run(*args)

    def attach(self, pane_id: str) -> None:
        """Attach the current terminal to the session that owns *pane_id*.

        This replaces the current process with ``tmux attach-session``.
        The caller should only invoke this interactively (not from a daemon).
        """
        # Resolve session name from pane_id.
        session_name: Optional[str] = None
        for pane in self.list_panes():
            if pane.pane_id == pane_id:
                session_name = pane.session_name
                break

        if session_name is None:
            log.error("Cannot attach: pane %s not found", pane_id)
            return

        import os
        os.execvp("tmux", ["tmux", "-L", self.socket, "attach-session", "-t", session_name])
