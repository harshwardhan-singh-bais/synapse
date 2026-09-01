"""
Git worktree operations for isolated parallel stage execution.

Each parallel stage runs in its own git worktree so file-level changes never
collide.  Successful stages are merged back to the base branch; failed or
cancelled stages have their worktrees pruned.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional


# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────────


def _git(args: list[str], cwd: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run a git command, returning the CompletedProcess result."""
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=check,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────


def create_worktree(
    repo_path: str,
    run_id: str,
    stage_index: int,
) -> tuple[Path, str]:
    """Create an isolated git worktree for a parallel stage.

    Returns ``(worktree_path, branch_name)``.
    Branch name: ``synapse-worktree-{run_id[:8]}-{stage_index}``
    """
    branch = f"synapse-worktree-{run_id[:8]}-{stage_index}"
    worktree_path = Path(repo_path) / ".synapse-worktrees" / branch

    worktree_path.parent.mkdir(parents=True, exist_ok=True)

    _git(
        ["worktree", "add", "-b", branch, str(worktree_path)],
        cwd=repo_path,
    )
    return worktree_path, branch


def merge_worktree_branch(
    repo_path: str,
    branch: str,
    base_branch: str = "main",
) -> tuple[bool, list[str]]:
    """Merge *branch* back into *base_branch*.

    Returns ``(True, [])`` on success.
    Returns ``(False, [conflict_files])`` on merge conflict so the caller
    can hand the conflict list to an agent for resolution.
    """
    success, conflicts = resolve_worktree_conflicts(repo_path, branch, base_branch)
    return success, conflicts


def remove_worktree(
    repo_path: str,
    worktree_path: str,
    branch: str,
) -> bool:
    """Remove a worktree and delete its tracking branch.

    Returns ``True`` on success.
    """
    try:
        _git(["worktree", "remove", "--force", worktree_path], cwd=repo_path)
        _git(["branch", "-D", branch], cwd=repo_path)
        return True
    except subprocess.CalledProcessError:
        return False


def cleanup_stale_worktrees(
    repo_path: str,
    run_id_prefix: str = "synapse-worktree-",
) -> None:
    """Find and remove any leftover Synapse worktrees from interrupted runs.

    Iterates over all worktrees reported by ``git worktree list`` and removes
    those whose branch name starts with *run_id_prefix*.
    """
    result = _git(["worktree", "list", "--porcelain"], cwd=repo_path, check=False)
    if result.returncode != 0:
        return

    worktree_path: Optional[str] = None
    branch: Optional[str] = None

    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith("worktree "):
            worktree_path = line[len("worktree "):]
            branch = None
        elif line.startswith("branch refs/heads/"):
            branch = line[len("branch refs/heads/"):]
        elif line == "" and worktree_path and branch:
            if branch.startswith(run_id_prefix):
                remove_worktree(repo_path, worktree_path, branch)
            worktree_path = None
            branch = None


def check_clean_tree(repo_path: str) -> tuple[bool, str]:
    """Check whether the git working tree has no uncommitted changes.

    Returns ``(is_clean, status_output)``.  A clean tree is required before
    unattended orchestration runs so that auto-commits record only the agent's
    changes.
    """
    result = _git(["status", "--porcelain"], cwd=repo_path, check=False)
    if result.returncode != 0:
        return False, result.stderr.strip()
    status = result.stdout.strip()
    return (status == "", status)


def auto_commit(
    repo_path: str,
    message: str = "synapse: auto-commit before run",
) -> bool:
    """Stage all changes and create a commit.

    Returns ``True`` on success.
    """
    try:
        _git(["add", "-A"], cwd=repo_path)
        _git(["commit", "-m", message], cwd=repo_path)
        return True
    except subprocess.CalledProcessError:
        return False


def strip_pyckle_from_index(repo_path: str) -> bool:
    """Remove pyckle files from the git index (cached).

    Pyckle files are serialized Python objects that may have been accidentally
    staged.  This function removes them from the index without deleting the
    files from the working tree.

    Returns ``True`` on success (or if no pyckle files were found).
    """
    try:
        # Check if there are any pyckle files in the index
        result = _git(
            ["ls-files", "--cached", "*.pyckle", "*.pickle"],
            cwd=repo_path,
            check=False,
        )
        if result.returncode != 0 or not result.stdout.strip():
            # No pyckle files found
            return True

        # Remove pyckle files from index (keep in working tree)
        _git(["rm", "--cached", "-r", "*.pyckle"], cwd=repo_path)
        _git(["rm", "--cached", "-r", "*.pickle"], cwd=repo_path)

        # Commit the removal
        _git(
            ["commit", "-m", "synapse: strip pyckle files from index"],
            cwd=repo_path,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def resolve_worktree_conflicts(
    repo_path: str,
    branch: str,
    base_branch: str = "main",
) -> tuple[bool, list[str]]:
    """Attempt to merge *branch* into *base_branch* and return any conflicts.

    If the merge succeeds, returns ``(True, [])``.
    If there are conflicts, aborts the merge and returns ``(False, [files])``
    so the caller can hand the conflict list to an agent for resolution.

    Returns ``(success, conflicting_files)``.
    """
    try:
        _git(["checkout", base_branch], cwd=repo_path)
        _git(
            ["merge", "--no-ff", branch, "-m", f"synapse: merge {branch}"],
            cwd=repo_path,
        )
        return True, []
    except subprocess.CalledProcessError:
        # Capture the list of conflicting files before aborting
        diff_result = _git(
            ["diff", "--name-only", "--diff-filter=U"],
            cwd=repo_path,
            check=False,
        )
        conflicts = [
            f for f in diff_result.stdout.strip().splitlines() if f
        ]
        # Abort to leave the repo in a clean state
        _git(["merge", "--abort"], cwd=repo_path, check=False)
        return False, conflicts


def build_conflict_resolution_prompt(
    conflicts: list[str],
    branch: str,
    base_branch: str = "main",
) -> str:
    """Build a prompt for an agent to resolve merge conflicts.

    The agent should read the conflicting files, understand both sides,
    and produce a resolution.  This is a *read-only* analysis prompt —
    the agent reports what it would do; the caller decides whether to
    act on it.
    """
    file_list = "\n".join(f"  - {f}" for f in conflicts)
    return (
        f"# Merge Conflict Resolution\n\n"
        f"Branch ``{branch}`` has conflicts with ``{base_branch}`` in the "
        f"following files:\n{file_list}\n\n"
        f"Please analyse each conflict and describe how to resolve it. "
        f"For each file:\n"
        f"1. Summarise what each side changed.\n"
        f"2. Propose a merged result that keeps the intent of both sides.\n"
        f"3. Flag any semantic conflicts that cannot be auto-merged.\n\n"
        f"Do NOT edit files — only report your analysis."
    )
