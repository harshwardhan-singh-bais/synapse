"""XDG-style path constants for Synapse."""

from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "synapse"
DATA_DIR = Path.home() / ".local" / "share" / "synapse"
WORKTREES_DIR = DATA_DIR / "worktrees"
RUNS_DIR = DATA_DIR / "runs"


def ensure_dirs() -> None:
    """Create all required Synapse directories if they do not already exist."""
    for d in [CONFIG_DIR, DATA_DIR, WORKTREES_DIR, RUNS_DIR]:
        d.mkdir(parents=True, exist_ok=True)
