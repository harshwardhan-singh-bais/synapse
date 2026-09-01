"""
Agent launcher — spawns agent processes with terminal presets, per-tool args,
environment injection, and runner script generation.

Ported from hcom's launcher.rs and terminal.rs.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..core.config import AgentDef, SynapseConfig
from ..core.paths import DATA_DIR


# ──────────────────────────────────────────────────────────────────────────────
# Terminal presets
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class TerminalPreset:
    """Definition of a terminal emulator preset."""
    name: str
    open_cmd: list[str]  # command to open a new window/tab
    close_cmd: Optional[list[str]] = None  # command to close
    platforms: list[str] = field(default_factory=lambda: ["linux", "darwin", "windows"])
    binary: Optional[str] = None
    app_name: Optional[str] = None


# Built-in terminal presets
TERMINAL_PRESETS: dict[str, TerminalPreset] = {
    "tmux": TerminalPreset(
        name="tmux",
        open_cmd=["tmux", "new-window"],
        platforms=["linux", "darwin"],
    ),
    "kitty": TerminalPreset(
        name="kitty",
        open_cmd=["kitty"],
        platforms=["linux", "darwin"],
    ),
    "wezterm": TerminalPreset(
        name="wezterm",
        open_cmd=["wezterm", "start"],
        platforms=["linux", "darwin", "windows"],
    ),
    "iterm": TerminalPreset(
        name="iterm",
        open_cmd=["open", "-a", "iTerm"],
        platforms=["darwin"],
    ),
    "alacritty": TerminalPreset(
        name="alacritty",
        open_cmd=["alacritty"],
        platforms=["linux", "darwin"],
    ),
    "ghostty": TerminalPreset(
        name="ghostty",
        open_cmd=["ghostty"],
        platforms=["linux", "darwin"],
    ),
}


# ──────────────────────────────────────────────────────────────────────────────
# Launcher
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class LaunchResult:
    """Result of launching an agent process."""
    success: bool
    process_id: Optional[int] = None
    instance_name: Optional[str] = None
    terminal_preset: Optional[str] = None
    error: Optional[str] = None
    runner_script: Optional[str] = None


class AgentLauncher:
    """Launches agent processes with the appropriate terminal and environment."""

    def __init__(self, config: SynapseConfig) -> None:
        self.config = config

    def launch(
        self,
        agent: AgentDef,
        instance_name: str,
        cwd: str,
        tag: Optional[str] = None,
        terminal: Optional[str] = None,
        headless: bool = False,
        extra_env: Optional[dict[str, str]] = None,
    ) -> LaunchResult:
        """Launch an agent process.

        Args:
            agent: Agent definition from agents.toml.
            instance_name: Unique name for this instance.
            cwd: Working directory.
            tag: Optional group tag.
            terminal: Terminal preset override.
            headless: If True, run without opening a terminal window.
            extra_env: Additional environment variables.

        Returns:
            LaunchResult with process info.
        """
        # Build environment
        env = self._build_env(agent, instance_name, tag, extra_env)

        # Build command
        cmd = self._build_command(agent, instance_name, cwd)

        # Determine terminal preset
        terminal_name = terminal or self.config.terminal or "tmux"

        if headless:
            return self._launch_headless(cmd, env, cwd, instance_name)
        else:
            return self._launch_terminal(cmd, env, cwd, instance_name, terminal_name)

    def _build_env(
        self,
        agent: AgentDef,
        instance_name: str,
        tag: Optional[str],
        extra_env: Optional[dict[str, str]],
    ) -> dict[str, str]:
        """Build environment variables for the agent process."""
        env = os.environ.copy()

        # Synapse identity
        env["SYNAPSE_INSTANCE_NAME"] = instance_name
        env["HCOM_INSTANCE_NAME"] = instance_name  # compat

        if tag:
            env["SYNAPSE_TAG"] = tag
            env["HCOM_TAG"] = tag  # compat

        # Agent-specific env
        if agent.env:
            env.update(agent.env)

        # Extra env
        if extra_env:
            env.update(extra_env)

        # Remove sensitive vars for child processes
        for key in ["SYNAPSE_PROCESS_ID", "HCOM_PROCESS_ID"]:
            env.pop(key, None)

        return env

    def _build_command(self, agent: AgentDef, instance_name: str, cwd: str) -> list[str]:
        """Build the command to launch the agent."""
        command = agent.command or agent.name
        args: list[str] = []

        # Handle resume args
        if agent.model and hasattr(agent, "resume_args"):
            resume_args = getattr(agent, "resume_args", None)
            if resume_args and instance_name:
                for arg in resume_args:
                    arg = arg.replace("{id}", instance_name)
                    args.append(arg)

        return [command] + args

    def _launch_terminal(
        self,
        cmd: list[str],
        env: dict[str, str],
        cwd: str,
        instance_name: str,
        terminal_name: str,
    ) -> LaunchResult:
        """Launch agent in a terminal window."""
        preset = TERMINAL_PRESETS.get(terminal_name)

        if preset:
            return self._launch_with_preset(preset, cmd, env, cwd, instance_name)
        else:
            # Try as a custom command
            return self._launch_custom_terminal(terminal_name, cmd, env, cwd, instance_name)

    def _launch_with_preset(
        self,
        preset: TerminalPreset,
        cmd: list[str],
        env: dict[str, str],
        cwd: str,
        instance_name: str,
    ) -> LaunchResult:
        """Launch agent using a terminal preset."""
        platform = sys.platform
        platform_name = "windows" if platform == "win32" else ("darwin" if platform == "darwin" else "linux")

        if platform_name not in preset.platforms:
            return LaunchResult(
                success=False,
                error=f"Terminal preset '{preset.name}' is not available on {platform_name}",
            )

        # Build the full command for the terminal
        full_cmd = cmd
        runner_script = self._write_runner_script(full_cmd, env, cwd, instance_name)

        # Build terminal open command
        open_cmd = list(preset.open_cmd)

        if preset.name == "tmux":
            # tmux specific: create a named session
            open_cmd.extend(["-s", f"synapse-{instance_name}", "-c", cwd])
            # We'll send the command via tmux send-keys after creating
            try:
                subprocess.Popen(
                    ["tmux", "new-session", "-d", "-s", f"synapse-{instance_name}", "-c", cwd],
                    env=env,
                )
                time.sleep(0.5)
                # Send the command
                cmd_str = " ".join(shlex.quote(c) for c in cmd)
                subprocess.Popen(
                    ["tmux", "send-keys", "-t", f"synapse-{instance_name}", cmd_str, "Enter"],
                    env=env,
                )
                return LaunchResult(
                    success=True,
                    terminal_preset=preset.name,
                    instance_name=instance_name,
                    runner_script=runner_script,
                )
            except FileNotFoundError:
                return LaunchResult(success=False, error="tmux not found")

        elif preset.name in ("kitty", "wezterm", "alacritty", "ghostty"):
            # These terminals can run a command directly
            open_cmd.extend(["--", "sh", runner_script])
            try:
                proc = subprocess.Popen(
                    open_cmd,
                    env=env,
                    cwd=cwd,
                    start_new_session=True,
                )
                return LaunchResult(
                    success=True,
                    process_id=proc.pid,
                    terminal_preset=preset.name,
                    instance_name=instance_name,
                    runner_script=runner_script,
                )
            except FileNotFoundError:
                return LaunchResult(
                    success=False,
                    error=f"Terminal binary not found: {preset.open_cmd[0]}",
                )

        elif preset.name == "iterm":
            # macOS: use osascript to open iTerm
            try:
                subprocess.Popen(
                    ["open", "-a", "iTerm"],
                    env=env,
                    start_new_session=True,
                )
                return LaunchResult(
                    success=True,
                    terminal_preset=preset.name,
                    instance_name=instance_name,
                    runner_script=runner_script,
                )
            except FileNotFoundError:
                return LaunchResult(success=False, error="macOS 'open' command not found")

        return LaunchResult(success=False, error=f"Unsupported preset: {preset.name}")

    def _launch_custom_terminal(
        self,
        terminal_cmd: str,
        cmd: list[str],
        env: dict[str, str],
        cwd: str,
        instance_name: str,
    ) -> LaunchResult:
        """Launch agent using a custom terminal command."""
        runner_script = self._write_runner_script(cmd, env, cwd, instance_name)

        # Parse the terminal command with {script} placeholder
        if "{script}" in terminal_cmd:
            terminal_cmd = terminal_cmd.replace("{script}", runner_script)

        try:
            parts = shlex.split(terminal_cmd)
            proc = subprocess.Popen(
                parts,
                env=env,
                cwd=cwd,
                start_new_session=True,
            )
            return LaunchResult(
                success=True,
                process_id=proc.pid,
                instance_name=instance_name,
                runner_script=runner_script,
            )
        except Exception as exc:
            return LaunchResult(success=False, error=str(exc))

    def _launch_headless(
        self,
        cmd: list[str],
        env: dict[str, str],
        cwd: str,
        instance_name: str,
    ) -> LaunchResult:
        """Launch agent in headless/background mode (no terminal window)."""
        runner_script = self._write_runner_script(cmd, env, cwd, instance_name)

        try:
            proc = subprocess.Popen(
                ["sh", runner_script],
                env=env,
                cwd=cwd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return LaunchResult(
                success=True,
                process_id=proc.pid,
                instance_name=instance_name,
                runner_script=runner_script,
            )
        except Exception as exc:
            return LaunchResult(success=False, error=str(exc))

    def _write_runner_script(
        self,
        cmd: list[str],
        env: dict[str, str],
        cwd: str,
        instance_name: str,
    ) -> str:
        """Write a runner script to disk and return its path."""
        script_dir = DATA_DIR / "scripts"
        script_dir.mkdir(parents=True, exist_ok=True)

        script_path = script_dir / f"runner-{instance_name}.sh"

        lines = ["#!/bin/bash"]
        lines.append(f"# Runner script for Synapse instance: {instance_name}")
        lines.append(f"cd {shlex.quote(cwd)}")

        # Set env vars
        for key, value in env.items():
            if key.startswith("SYNAPSE_") or key.startswith("HCOM_"):
                lines.append(f"export {key}={shlex.quote(value)}")

        # Execute the command
        cmd_str = " ".join(shlex.quote(c) for c in cmd)
        lines.append(f"exec {cmd_str}")

        script_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.chmod(script_path, 0o755)

        return str(script_path)


# Need to import time for tmux preset
import time
