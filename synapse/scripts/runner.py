"""
Workflow script runner — discovers and executes user workflow scripts.

Ported from hcom's scripts.rs.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional

from ..core.paths import CONFIG_DIR


SCRIPTS_DIR = CONFIG_DIR / "scripts"


def discover_scripts() -> list[dict[str, str]]:
    """Discover available workflow scripts."""
    scripts = []

    # Built-in scripts
    builtins = {
        "status": "Show overall status",
        "list": "List all sessions",
        "inbox": "Check inbox for current session",
        "send": "Send a message to a session",
    }

    for name, desc in builtins.items():
        scripts.append({
            "name": name,
            "description": desc,
            "source": "builtin",
        })

    # User scripts from ~/.config/synapse/scripts/
    if SCRIPTS_DIR.exists():
        for path in SCRIPTS_DIR.iterdir():
            if path.suffix in (".sh", ".py", ".ps1") and not path.name.startswith("."):
                scripts.append({
                    "name": path.stem,
                    "description": f"User script: {path.name}",
                    "source": str(path),
                })

    return scripts


def run_script(
    name: str,
    args: Optional[list[str]] = None,
    env: Optional[dict[str, str]] = None,
    cwd: Optional[str] = None,
) -> subprocess.CompletedProcess:
    """Run a workflow script by name."""
    # Check built-in scripts first
    if name == "status":
        return subprocess.run(
            ["python", "-m", "synapse", "status"],
            capture_output=True,
            text=True,
        )
    elif name == "list":
        return subprocess.run(
            ["python", "-m", "synapse", "session", "list"],
            capture_output=True,
            text=True,
        )

    # Check user scripts
    script_path = SCRIPTS_DIR / name
    for ext in [".sh", ".py", ".ps1", ""]:
        candidate = script_path.with_suffix(script_path.suffix + ext) if ext else script_path
        if candidate.exists():
            cmd = [str(candidate)] + (args or [])
            return subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                env={**os.environ, **(env or {})} if env else None,
                cwd=cwd,
            )

    # Try as a shell command
    return subprocess.run(
        ["sh", "-c", name] + (args or []),
        capture_output=True,
        text=True,
    )
