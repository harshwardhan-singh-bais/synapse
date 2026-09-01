"""
Windows PTY spawn using ConPTY (Console Pseudo Terminal).

This module provides Windows-specific PTY support using the ConPTY API,
which allows creating pseudo-terminal sessions on Windows.

Requires:
- Windows 10 version 1809 or later
- ctypes (built-in Python module)

Note: This is an alternative to the Unix pty module used in proxy.py.
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

log = logging.getLogger(__name__)

# Check if we're on Windows
IS_WINDOWS = sys.platform == "win32"

# Windows constants
INVALID_HANDLE_VALUE = ctypes.wintypes.HANDLE(-1).value
ERROR_SUCCESS = 0
STARTF_USESTDHANDLES = 0x00000100
CREATE_NEW_CONSOLE = 0x00000010
CREATE_UNICODE_ENVIRONMENT = 0x00000400

# Console API constants
ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
DISABLE_NEWLINE_AUTO_RETURN = 0x0008

# Flag for ConPTY
PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE = 0x00020016


if IS_WINDOWS:
    # Define Windows structures that aren't in ctypes.wintypes
    class COORD(ctypes.Structure):
        _fields_ = [
            ("X", ctypes.c_short),
            ("Y", ctypes.c_short),
        ]

    class STARTUPINFOW(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.wintypes.DWORD),
            ("lpReserved", ctypes.wintypes.LPWSTR),
            ("lpDesktop", ctypes.wintypes.LPWSTR),
            ("lpTitle", ctypes.wintypes.LPWSTR),
            ("dwX", ctypes.wintypes.DWORD),
            ("dwY", ctypes.wintypes.DWORD),
            ("dwXSize", ctypes.wintypes.DWORD),
            ("dwYSize", ctypes.wintypes.DWORD),
            ("dwXCountChars", ctypes.wintypes.DWORD),
            ("dwYCountChars", ctypes.wintypes.DWORD),
            ("dwFillAttribute", ctypes.wintypes.DWORD),
            ("dwFlags", ctypes.wintypes.DWORD),
            ("wShowWindow", ctypes.wintypes.WORD),
            ("cbReserved2", ctypes.wintypes.WORD),
            ("lpReserved2", ctypes.c_void_p),
            ("hStdInput", ctypes.wintypes.HANDLE),
            ("hStdOutput", ctypes.wintypes.HANDLE),
            ("hStdError", ctypes.wintypes.HANDLE),
        ]

    class PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("hProcess", ctypes.wintypes.HANDLE),
            ("hThread", ctypes.wintypes.HANDLE),
            ("dwProcessId", ctypes.wintypes.DWORD),
            ("dwThreadId", ctypes.wintypes.DWORD),
        ]

    # Windows API functions
    kernel32 = ctypes.windll.kernel32

    # Console creation
    CreatePipe = kernel32.CreatePipe
    CreatePipe.argtypes = [
        ctypes.POINTER(ctypes.wintypes.HANDLE),
        ctypes.POINTER(ctypes.wintypes.HANDLE),
        ctypes.wintypes.LPVOID,
        ctypes.wintypes.DWORD,
    ]
    CreatePipe.restype = ctypes.wintypes.BOOL

    CreateProcess = kernel32.CreateProcessW
    CreateProcess.argtypes = [
        ctypes.wintypes.LPCWSTR,
        ctypes.wintypes.LPWSTR,
        ctypes.wintypes.LPVOID,
        ctypes.wintypes.LPVOID,
        ctypes.wintypes.BOOL,
        ctypes.wintypes.DWORD,
        ctypes.wintypes.LPVOID,
        ctypes.wintypes.LPCWSTR,
        ctypes.POINTER(STARTUPINFOW),
        ctypes.POINTER(PROCESS_INFORMATION),
    ]
    CreateProcess.restype = ctypes.wintypes.BOOL

    CloseHandle = kernel32.CloseHandle
    CloseHandle.argtypes = [ctypes.wintypes.HANDLE]
    CloseHandle.restype = ctypes.wintypes.BOOL

    ReadFile = kernel32.ReadFile
    ReadFile.argtypes = [
        ctypes.wintypes.HANDLE,
        ctypes.wintypes.LPVOID,
        ctypes.wintypes.DWORD,
        ctypes.POINTER(ctypes.wintypes.DWORD),
        ctypes.wintypes.LPVOID,
    ]
    ReadFile.restype = ctypes.wintypes.BOOL

    WriteFile = kernel32.WriteFile
    WriteFile.argtypes = [
        ctypes.wintypes.HANDLE,
        ctypes.wintypes.LPCVOID,
        ctypes.wintypes.DWORD,
        ctypes.POINTER(ctypes.wintypes.DWORD),
        ctypes.wintypes.LPVOID,
    ]
    WriteFile.restype = ctypes.wintypes.BOOL

    GetExitCodeProcess = kernel32.GetExitCodeProcess
    GetExitCodeProcess.argtypes = [
        ctypes.wintypes.HANDLE,
        ctypes.POINTER(ctypes.wintypes.DWORD),
    ]
    GetExitCodeProcess.restype = ctypes.wintypes.BOOL

    WaitForSingleObject = kernel32.WaitForSingleObject
    WaitForSingleObject.argtypes = [ctypes.wintypes.HANDLE, ctypes.wintypes.DWORD]
    WaitForSingleObject.restype = ctypes.wintypes.DWORD

    # Try to import ConPTY functions (Windows 10 1809+)
    try:
        CreatePseudoConsole = kernel32.CreatePseudoConsole
        CreatePseudoConsole.argtypes = [
            COORD,
            ctypes.wintypes.HANDLE,
            ctypes.wintypes.HANDLE,
            ctypes.wintypes.DWORD,
            ctypes.POINTER(ctypes.wintypes.HANDLE),
        ]
        CreatePseudoConsole.restype = ctypes.wintypes.HANDLE

        ResizePseudoConsole = kernel32.ResizePseudoConsole
        ResizePseudoConsole.argtypes = [
            ctypes.wintypes.HANDLE,
            COORD,
        ]
        ResizePseudoConsole.restype = ctypes.wintypes.BOOL

        ClosePseudoConsole = kernel32.ClosePseudoConsole
        ClosePseudoConsole.argtypes = [ctypes.wintypes.HANDLE]
        ClosePseudoConsole.restype = None

        HAS_CONPTY = True
    except AttributeError:
        HAS_CONPTY = False
        log.warning("ConPTY API not available (requires Windows 10 1809+)")
else:
    HAS_CONPTY = False
    COORD = None
    STARTUPINFOW = None
    PROCESS_INFORMATION = None


# ──────────────────────────────────────────────────────────────────────────────
# Windows PTY wrapper
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class WindowsPtyConfig:
    """Configuration for Windows PTY spawn."""
    cols: int = 220
    rows: int = 50
    env_vars: Optional[dict[str, str]] = None


class WindowsPtyProxy:
    """
    Windows PTY proxy using ConPTY.

    Creates a pseudo-console and spawns a process inside it.
    Provides read/write access to the process's I/O.
    """

    def __init__(
        self,
        command: str,
        args: list[str],
        config: Optional[WindowsPtyConfig] = None,
        cwd: Optional[str] = None,
    ) -> None:
        if not IS_WINDOWS:
            raise RuntimeError("WindowsPtyProxy is only available on Windows")

        if not HAS_CONPTY:
            raise RuntimeError("ConPTY API not available (requires Windows 10 1809+)")

        self.command = command
        self.args = args
        self.config = config or WindowsPtyConfig()
        self.cwd = cwd or os.getcwd()

        self._h_process: Optional[ctypes.wintypes.HANDLE] = None
        self._h_thread: Optional[ctypes.wintypes.HANDLE] = None
        self._h_console: Optional[ctypes.wintypes.HANDLE] = None
        self._h_input: Optional[ctypes.wintypes.HANDLE] = None
        self._h_output: Optional[ctypes.wintypes.HANDLE] = None
        self._running = False
        self._exit_code: int = 0
        self._reader_thread: Optional[threading.Thread] = None
        self._output_callback: Optional[callable] = None

    def spawn(self) -> bool:
        """Spawn the process in a ConPTY."""
        try:
            # Create pipes for input/output
            h_input_read, h_input_write = self._create_pipe()
            h_output_read, h_output_write = self._create_pipe()

            # Create the pseudo console
            size = COORD(self.config.cols, self.config.rows)
            h_console = ctypes.wintypes.HANDLE()

            result = CreatePseudoConsole(
                size,
                h_input_read,
                h_output_write,
                0,
                ctypes.byref(h_console),
            )

            if not result:
                log.error("Failed to create pseudo console: %s", ctypes.get_last_error())
                return False

            self._h_console = h_console
            self._h_input = h_input_write
            self._h_output = h_output_read

            # Close the pipe ends we don't need
            CloseHandle(h_input_read)
            CloseHandle(h_output_write)

            # Set up the process
            startup_info = STARTUPINFOW()
            startup_info.cb = ctypes.sizeof(STARTUPINFOW)
            startup_info.hStdInput = h_input_read
            startup_info.hStdOutput = h_output_write
            startup_info.hStdError = h_output_write
            startup_info.dwFlags = STARTF_USESTDHANDLES

            process_info = PROCESS_INFORMATION()

            # Build the command line
            cmd_line = f'"{self.command}" {" ".join(self.args)}'

            # Build environment block
            env_block = self._build_env_block()

            # Create the process
            success = CreateProcess(
                None,
                ctypes.create_unicode_buffer(cmd_line),
                None,
                None,
                True,  # Inherit handles
                CREATE_NEW_CONSOLE | CREATE_UNICODE_ENVIRONMENT,
                env_block,
                self.cwd,
                ctypes.byref(startup_info),
                ctypes.byref(process_info),
            )

            if not success:
                log.error("Failed to create process: %s", ctypes.get_last_error())
                CloseHandle(h_console)
                return False

            self._h_process = process_info.hProcess
            self._h_thread = process_info.hThread
            self._running = True

            # Start reader thread
            self._reader_thread = threading.Thread(
                target=self._read_loop,
                daemon=True,
                name="winpty-reader",
            )
            self._reader_thread.start()

            log.info("Spawned process in ConPTY: %s", self.command)
            return True

        except Exception as exc:
            log.error("Failed to spawn Windows PTY: %s", exc)
            return False

    def _create_pipe(self) -> tuple:
        """Create a Windows pipe."""
        read_handle = ctypes.wintypes.HANDLE()
        write_handle = ctypes.wintypes.HANDLE()

        if not CreatePipe(
            ctypes.byref(read_handle),
            ctypes.byref(write_handle),
            None,
            0,
        ):
            raise RuntimeError("Failed to create pipe")

        return read_handle, write_handle

    def _build_env_block(self) -> Optional[ctypes.c_void_p]:
        """Build an environment block for the new process."""
        env = os.environ.copy()
        if self.config.env_vars:
            env.update(self.config.env_vars)

        # Convert to Windows environment block format
        env_strings = []
        for key, value in env.items():
            env_strings.append(f"{key}={value}")

        env_block = "\0".join(env_strings) + "\0\0"
        return ctypes.create_unicode_buffer(env_block)

    def _read_loop(self) -> None:
        """Background thread that reads output from the ConPTY."""
        buffer = ctypes.create_string_buffer(4096)
        bytes_read = ctypes.wintypes.DWORD()

        while self._running:
            success = ReadFile(
                self._h_output,
                buffer,
                4096,
                ctypes.byref(bytes_read),
                None,
            )

            if not success or bytes_read.value == 0:
                if not self._running:
                    break
                time.sleep(0.01)
                continue

            data = buffer.raw[:bytes_read.value]
            if self._output_callback:
                try:
                    self._output_callback(data)
                except Exception as exc:
                    log.error("Output callback error: %s", exc)

    def write(self, data: bytes) -> bool:
        """Write data to the ConPTY."""
        if not self._running or not self._h_input:
            return False

        bytes_written = ctypes.wintypes.DWORD()
        success = WriteFile(
            self._h_input,
            data,
            len(data),
            ctypes.byref(bytes_written),
            None,
        )

        return success and bytes_written.value == len(data)

    def write_text(self, text: str) -> bool:
        """Write text to the ConPTY."""
        return self.write(text.encode("utf-8"))

    def send_enter(self) -> bool:
        """Send Enter key."""
        return self.write(b"\r")

    def resize(self, cols: int, rows: int) -> bool:
        """Resize the pseudo console."""
        if not self._h_console:
            return False

        size = COORD(cols, rows)
        return bool(ResizePseudoConsole(self._h_console, size))

    def is_alive(self) -> bool:
        """Check if the process is still running."""
        if not self._h_process:
            return False

        exit_code = ctypes.wintypes.DWORD()
        if GetExitCodeProcess(self._h_process, ctypes.byref(exit_code)):
            return exit_code.value == 259  # STILL_ACTIVE
        return False

    def get_exit_code(self) -> int:
        """Get the process exit code."""
        if not self._h_process:
            return -1

        exit_code = ctypes.wintypes.DWORD()
        if GetExitCodeProcess(self._h_process, ctypes.byref(exit_code)):
            return exit_code.value
        return -1

    def set_output_callback(self, callback: callable) -> None:
        """Set a callback for output data."""
        self._output_callback = callback

    def cleanup(self) -> None:
        """Clean up resources."""
        self._running = False

        if self._reader_thread:
            self._reader_thread.join(timeout=2.0)

        if self._h_process:
            try:
                WaitForSingleObject(self._h_process, 1000)
                CloseHandle(self._h_process)
            except Exception:
                pass

        if self._h_thread:
            try:
                CloseHandle(self._h_thread)
            except Exception:
                pass

        if self._h_console:
            try:
                ClosePseudoConsole(self._h_console)
            except Exception:
                pass

        if self._h_input:
            try:
                CloseHandle(self._h_input)
            except Exception:
                pass

        if self._h_output:
            try:
                CloseHandle(self._h_output)
            except Exception:
                pass


# ──────────────────────────────────────────────────────────────────────────────
# Convenience function
# ──────────────────────────────────────────────────────────────────────────────


def spawn_windows_pty(
    command: str,
    args: list[str],
    cwd: Optional[str] = None,
    cols: int = 220,
    rows: int = 50,
    env_vars: Optional[dict[str, str]] = None,
) -> Optional[WindowsPtyProxy]:
    """
    Convenience function to spawn a Windows PTY.

    Returns a WindowsPtyProxy instance on success, None on failure.
    """
    if not IS_WINDOWS:
        log.error("spawn_windows_pty is only available on Windows")
        return None

    if not HAS_CONPTY:
        log.error("ConPTY API not available")
        return None

    config = WindowsPtyConfig(
        cols=cols,
        rows=rows,
        env_vars=env_vars,
    )

    proxy = WindowsPtyProxy(
        command=command,
        args=args,
        config=config,
        cwd=cwd,
    )

    if proxy.spawn():
        return proxy
    return None
