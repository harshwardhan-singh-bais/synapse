"""
Remote transport — SSH and WSL transport for tmux sessions.

Ported from thurbox's agent/transport.rs.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Optional


@dataclass
class HostConfig:
    """Configuration for a remote host."""
    name: str
    kind: str  # 'ssh' | 'wsl'
    destination: Optional[str] = None  # SSH target (user@host)
    distro: Optional[str] = None  # WSL distro name
    socket: str = "synapse"  # tmux socket name
    worktrees_dir: str = "~/.synapse/worktrees"
    multiplexer: str = "tmux"


class RemoteTransport:
    """Transport for running tmux commands on remote hosts."""

    def __init__(self, host: HostConfig) -> None:
        self.host = host

    def tmux_command(self, args: list[str]) -> list[str]:
        """Build a tmux command list for this transport."""
        if self.host.kind == "ssh":
            return self._ssh_tmux_command(args)
        elif self.host.kind == "wsl":
            return self._wsl_tmux_command(args)
        else:
            return ["tmux", "-L", self.host.socket] + args

    def _ssh_tmux_command(self, args: list[str]) -> list[str]:
        """Build SSH-wrapped tmux command."""
        tmux_cmd = " ".join(["tmux", "-L", self.host.socket] + args)
        return [
            "ssh",
            "-o", "StrictHostKeyChecking=no",
            self.host.destination or "",
            tmux_cmd,
        ]

    def _wsl_tmux_command(self, args: list[str]) -> list[str]:
        """Build WSL-wrapped tmux command."""
        tmux_cmd = " ".join(["tmux", "-L", self.host.socket] + args)
        return [
            "wsl",
            "-d", self.host.distro or "Ubuntu",
            "--",
            "sh", "-c", tmux_cmd,
        ]

    def run_tmux(self, args: list[str], timeout: int = 10) -> subprocess.CompletedProcess:
        """Run a tmux command on the remote host."""
        cmd = self.tmux_command(args)
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def is_reachable(self) -> bool:
        """Check if the remote host is reachable."""
        try:
            if self.host.kind == "ssh":
                result = subprocess.run(
                    ["ssh", "-o", "ConnectTimeout=5", self.host.destination or "", "echo ok"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                return result.returncode == 0
            elif self.host.kind == "wsl":
                result = subprocess.run(
                    ["wsl", "-d", self.host.distro or "Ubuntu", "--", "echo", "ok"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False
        return True


def load_hosts_from_config() -> list[HostConfig]:
    """Load host configurations from ~/.config/synapse/hosts.toml."""
    import tomllib
    from ..core.paths import CONFIG_DIR

    hosts_path = CONFIG_DIR / "hosts.toml"
    if not hosts_path.exists():
        return []

    try:
        with hosts_path.open("rb") as fh:
            raw = tomllib.load(fh)
    except Exception:
        return []

    hosts = []
    for entry in raw.get("hosts", []):
        if isinstance(entry, dict):
            hosts.append(HostConfig(
                name=entry.get("name", "unknown"),
                kind=entry.get("kind", "ssh"),
                destination=entry.get("destination"),
                distro=entry.get("distro"),
                socket=entry.get("socket", "synapse"),
                worktrees_dir=entry.get("worktrees_dir", "~/.synapse/worktrees"),
                multiplexer=entry.get("multiplexer", "tmux"),
            ))

    return hosts
