"""Clipboard — cross-platform clipboard abstraction."""
from __future__ import annotations

import subprocess
import sys
from typing import Optional


def copy_to_clipboard(text: str) -> bool:
    """Copy text to the system clipboard."""
    try:
        if sys.platform == "win32":
            process = subprocess.Popen(
                ["clip"],
                stdin=subprocess.PIPE,
            )
            process.communicate(input=text.encode("utf-16-le"))
            return process.returncode == 0
        elif sys.platform == "darwin":
            process = subprocess.Popen(
                ["pbcopy"],
                stdin=subprocess.PIPE,
            )
            process.communicate(input=text.encode("utf-8"))
            return process.returncode == 0
        else:
            # Linux: try xclip, then xsel
            for cmd in [["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]]:
                try:
                    process = subprocess.Popen(
                        cmd,
                        stdin=subprocess.PIPE,
                    )
                    process.communicate(input=text.encode("utf-8"))
                    if process.returncode == 0:
                        return True
                except FileNotFoundError:
                    continue
            return False
    except Exception:
        return False


def paste_from_clipboard() -> Optional[str]:
    """Paste text from the system clipboard."""
    try:
        if sys.platform == "win32":
            process = subprocess.Popen(
                ["powershell", "-command", "Get-Clipboard"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            stdout, _ = process.communicate(timeout=5)
            return stdout.decode("utf-8").strip() if process.returncode == 0 else None
        elif sys.platform == "darwin":
            process = subprocess.Popen(
                ["pbpaste"],
                stdout=subprocess.PIPE,
            )
            stdout, _ = process.communicate(timeout=5)
            return stdout.decode("utf-8") if process.returncode == 0 else None
        else:
            for cmd in [["xclip", "-selection", "clipboard", "-o"], ["xsel", "--clipboard", "--output"]]:
                try:
                    process = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                    )
                    stdout, _ = process.communicate(timeout=5)
                    if process.returncode == 0:
                        return stdout.decode("utf-8")
                except FileNotFoundError:
                    continue
            return None
    except Exception:
        return None
