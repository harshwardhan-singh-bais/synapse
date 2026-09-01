"""
PTY proxy — wraps an agent process in a pseudo-terminal, tracks screen state,
provides TCP injection/query ports, and runs the delivery loop.

Ported from hcom's pty/mod.rs, pty/screen.rs, pty/inject.rs, and delivery.rs.
"""
from __future__ import annotations

import io
import json
import os
import pty
import select
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

try:
    import pyte
    HAS_PYTE = True
except ImportError:
    HAS_PYTE = False


# ──────────────────────────────────────────────────────────────────────────────
# Screen state tracker
# ──────────────────────────────────────────────────────────────────────────────


class ScreenState:
    """Tracks the virtual terminal screen state using pyte."""

    def __init__(self, cols: int = 220, rows: int = 50, instance_name: str = "") -> None:
        self.cols = cols
        self.rows = rows
        self.instance_name = instance_name
        self._last_output_time = time.monotonic()
        self._cursor_row = 0
        self._cursor_col = 0
        self._ready = False
        self._approval_visible = False
        self._child_title: Optional[str] = None

        if HAS_PYTE:
            self._screen = pyte.Screen(cols, rows)
            self._stream = pyte.Stream(self._screen)
        else:
            self._screen = None
            self._stream = None

    def process(self, data: bytes) -> None:
        """Process raw bytes from the PTY master."""
        self._last_output_time = time.monotonic()

        if self._stream and self._screen:
            try:
                text = data.decode("utf-8", errors="replace")
                self._stream.feed(text)
                self._cursor_row = self._screen.cursor.y
                self._cursor_col = self._screen.cursor.x
            except Exception:
                pass

        # Check for ready patterns (e.g., "? for shortcuts" for Claude)
        if self._screen:
            visible = self._get_visible_text()
            if "? for shortcuts" in visible or "claude" in visible.lower():
                self._ready = True

    def is_ready(self) -> bool:
        """Return True if the agent appears to be ready for input."""
        return self._ready

    def is_waiting_approval(self) -> bool:
        """Return True if an approval dialog is visible."""
        return self._approval_visible

    def is_output_stable(self, ms: int = 500) -> bool:
        """Return True if no output has arrived for at least `ms` milliseconds."""
        elapsed = (time.monotonic() - self._last_output_time) * 1000
        return elapsed >= ms

    def get_visible_text(self) -> str:
        """Return the visible text from the screen buffer."""
        return self._get_visible_text()

    def _get_visible_text(self) -> str:
        if not self._screen:
            return ""
        lines = []
        for row in range(self.rows):
            line = ""
            for col in range(self.cols):
                try:
                    char = self._screen.buffer[row][col]
                    line += char.data if hasattr(char, "data") else str(char)
                except (IndexError, AttributeError):
                    line += " "
            lines.append(line.rstrip())
        return "\n".join(lines)

    def resize(self, cols: int, rows: int) -> None:
        """Resize the virtual screen."""
        self.cols = cols
        self.rows = rows
        if self._screen:
            self._screen.resize(rows, cols)


# ──────────────────────────────────────────────────────────────────────────────
# Delivery state machine
# ──────────────────────────────────────────────────────────────────────────────


class DeliveryState(Enum):
    """States of the message delivery state machine."""
    IDLE = "idle"
    PENDING = "pending"
    WAIT_TEXT_RENDER = "wait_text_render"
    WAIT_TEXT_CLEAR = "wait_text_clear"
    VERIFY_CURSOR = "verify_cursor"


# ──────────────────────────────────────────────────────────────────────────────
# TCP inject/query server
# ──────────────────────────────────────────────────────────────────────────────


class InjectServer:
    """TCP server that accepts text injection and state query requests."""

    def __init__(self) -> None:
        self._server: Optional[socket.socket] = None
        self._port: int = 0
        self._clients: list[socket.socket] = []
        self._on_inject: Optional[Callable[[str], None]] = None
        self._on_query: Optional[Callable[[], str]] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def start(
        self,
        on_inject: Optional[Callable[[str], None]] = None,
        on_query: Optional[Callable[[], str]] = None,
    ) -> int:
        """Start the inject server on a random port. Returns the port number."""
        self._on_inject = on_inject
        self._on_query = on_query

        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(5)
        self._port = self._server.getsockname()[1]
        self._running = True

        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

        return self._port

    def stop(self) -> None:
        """Stop the server."""
        self._running = False
        if self._server:
            try:
                self._server.close()
            except Exception:
                pass

    def _run(self) -> None:
        while self._running and self._server:
            try:
                self._server.settimeout(1.0)
                client, addr = self._server.accept()
                self._clients.append(client)
                threading.Thread(
                    target=self._handle_client, args=(client,), daemon=True
                ).start()
            except socket.timeout:
                continue
            except OSError:
                break

    def _handle_client(self, client: socket.socket) -> None:
        try:
            data = b""
            while True:
                chunk = client.recv(4096)
                if not chunk:
                    break
                data += chunk
                if b"\n" in data:
                    break

            request = data.decode("utf-8", errors="replace").strip()

            if request.startswith("INJECT:"):
                text = request[7:]
                if self._on_inject:
                    self._on_inject(text)
                client.sendall(b"OK\n")
            elif request.startswith("QUERY"):
                if self._on_query:
                    response = self._on_query()
                    client.sendall(response.encode("utf-8") + b"\n")
                else:
                    client.sendall(b"{}\n")
            else:
                client.sendall(b"ERR unknown command\n")
        except Exception:
            pass
        finally:
            try:
                client.close()
            except Exception:
                pass


# ──────────────────────────────────────────────────────────────────────────────
# PTY Proxy
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class ProxyConfig:
    """Configuration for a PTY proxy."""
    ready_pattern: list[str] = field(default_factory=list)
    instance_name: str = ""
    env_vars: list[tuple[str, str]] = field(default_factory=list)


class PtyProxy:
    """Wraps an agent process in a PTY, tracks screen state, and runs delivery."""

    def __init__(
        self,
        command: str,
        args: list[str],
        config: ProxyConfig,
        cwd: Optional[str] = None,
    ) -> None:
        self.command = command
        self.args = args
        self.config = config
        self.cwd = cwd or os.getcwd()

        self._master_fd: Optional[int] = None
        self._slave_fd: Optional[int] = None
        self._pid: Optional[int] = None
        self._screen = ScreenState(instance_name=config.instance_name)
        self._inject_server = InjectServer()
        self._running = False
        self._exit_code: int = 0

        # Delivery
        self._delivery_state = DeliveryState.IDLE
        self._pending_text: Optional[str] = None

    def spawn(self) -> None:
        """Spawn the agent process in a PTY."""
        # Create PTY pair
        self._master_fd, self._slave_fd = pty.openpty()

        # Build environment
        env = os.environ.copy()
        for key, value in self.config.env_vars:
            env[key] = value
        env["HCOM_LAUNCHED"] = "1"

        # Fork
        self._pid = os.fork()
        if self._pid == 0:
            # Child process
            os.close(self._master_fd)
            os.setsid()

            # Redirect stdin/stdout/stderr to slave
            os.dup2(self._slave_fd, 0)
            os.dup2(self._slave_fd, 1)
            os.dup2(self._slave_fd, 2)
            if self._slave_fd > 2:
                os.close(self._slave_fd)

            # Execute
            full_cmd = [self.command] + self.args
            os.execvpe(full_cmd[0], full_cmd, env)
        else:
            # Parent process
            os.close(self._slave_fd)
            self._slave_fd = None
            self._running = True

            # Start inject server
            self._inject_server.start(
                on_inject=self._handle_inject,
                on_query=self._handle_query,
            )

    def run(self) -> int:
        """Run the proxy loop. Returns exit code."""
        if self._pid is None:
            return 1

        try:
            while self._running:
                # Check if child is alive
                pid, status = os.waitpid(self._pid, os.WNOHANG)
                if pid != 0:
                    self._exit_code = os.WEXITSTATUS(status) if os.WIFEXITED(status) else 1
                    self._running = False
                    break

                # Read from PTY
                if self._master_fd is not None:
                    readable, _, _ = select.select([self._master_fd], [], [], 0.1)
                    if readable:
                        try:
                            data = os.read(self._master_fd, 4096)
                            if data:
                                self._screen.process(data)
                                # Write to real stdout (passthrough)
                                sys.stdout.buffer.write(data)
                                sys.stdout.buffer.flush()
                        except OSError:
                            break

        except KeyboardInterrupt:
            self._running = False
        finally:
            self.cleanup()

        return self._exit_code

    def cleanup(self) -> None:
        """Clean up resources."""
        self._inject_server.stop()
        if self._master_fd is not None:
            try:
                os.close(self._master_fd)
            except OSError:
                pass
        if self._pid:
            try:
                os.kill(self._pid, signal.SIGTERM)
                time.sleep(0.5)
                os.kill(self._pid, signal.SIGKILL)
            except (OSError, ProcessLookupError):
                pass

    def inject_text(self, text: str) -> None:
        """Inject text into the PTY."""
        if self._master_fd is not None:
            try:
                os.write(self._master_fd, text.encode("utf-8"))
            except OSError:
                pass

    def inject_enter(self) -> None:
        """Send Enter keystroke."""
        if self._master_fd is not None:
            try:
                os.write(self._master_fd, b"\r")
            except OSError:
                pass

    def get_screen_text(self) -> str:
        """Get visible screen text."""
        return self._screen.get_visible_text()

    def is_ready(self) -> bool:
        """Check if agent is ready for input."""
        return self._screen.is_ready()

    def _handle_inject(self, text: str) -> None:
        """Handle text injection from TCP server."""
        self.inject_text(text)

    def _handle_query(self) -> str:
        """Handle state query from TCP server."""
        return json.dumps({
            "ready": self._screen.is_ready(),
            "approval": self._screen.is_waiting_approval(),
            "screen": self._screen.get_visible_text()[:500],
        })
