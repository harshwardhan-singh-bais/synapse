"""
Multi-repo workspace builder — creates a directory of symlinks pointing at
each member repository's checkout. The agent's CWD is this workspace directory.

Ported from thurbox's workspace.rs.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from ..core.paths import DATA_DIR


WORKSPACES_DIR = DATA_DIR / "workspaces"


def build_workspace(
    session_id: str,
    repos: list[dict[str, str]],
    base_dir: Optional[Path] = None,
) -> Path:
    """Build a multi-repo workspace for a session.

    Args:
        session_id: The session's unique ID.
        repos: List of dicts with 'path' (repo checkout path) and
               optional 'base' (base name for the symlink).
        base_dir: Override for the workspaces directory.

    Returns:
        Path to the workspace directory.
    """
    workspace_dir = (base_dir or WORKSPACES_DIR) / session_id
    workspace_dir.mkdir(parents=True, exist_ok=True)

    for repo in repos:
        repo_path = Path(repo["path"])
        base_name = repo.get("base") or repo_path.name

        symlink_path = workspace_dir / base_name

        # Remove existing symlink if present
        if symlink_path.exists() or symlink_path.is_symlink():
            if symlink_path.is_symlink():
                symlink_path.unlink()
            elif symlink_path.is_dir():
                import shutil
                shutil.rmtree(symlink_path)

        # Create symlink
        try:
            os.symlink(str(repo_path), str(symlink_path))
        except OSError:
            # Fallback: copy directory info
            symlink_path.mkdir(exist_ok=True)

    return workspace_dir


def cleanup_workspace(session_id: str, base_dir: Optional[Path] = None) -> bool:
    """Remove a session's workspace directory."""
    workspace_dir = (base_dir or WORKSPACES_DIR) / session_id
    if not workspace_dir.exists():
        return True

    import shutil
    try:
        shutil.rmtree(workspace_dir)
        return True
    except OSError:
        return False


def list_workspaces(base_dir: Optional[Path] = None) -> list[dict]:
    """List all active workspaces."""
    workspaces_dir = base_dir or WORKSPACES_DIR
    if not workspaces_dir.exists():
        return []

    result = []
    for entry in sorted(workspaces_dir.iterdir()):
        if entry.is_dir():
            links = []
            for item in entry.iterdir():
                if item.is_symlink():
                    links.append({
                        "name": item.name,
                        "target": str(item.resolve()),
                        "exists": item.exists(),
                    })
            result.append({
                "session_id": entry.name,
                "path": str(entry),
                "repos": len(links),
                "links": links,
            })

    return result
