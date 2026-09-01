"""Click commands for `synapse session`."""
from __future__ import annotations

import sys

import click

from ...backend.tmux import TmuxBackend
from ...core.config import SynapseConfig
from ...db.database import Database
from ...session.manager import SessionManager


# ──────────────────────────────────────────────────────────────────────────────
# Shared factory
# ──────────────────────────────────────────────────────────────────────────────


def get_managers(ctx: click.Context) -> tuple[SessionManager, Database]:
    config: SynapseConfig = ctx.obj["config"]
    db = Database(config.db_path)
    tmux = TmuxBackend()
    return SessionManager(db, tmux, config), db


# ──────────────────────────────────────────────────────────────────────────────
# Commands
# ──────────────────────────────────────────────────────────────────────────────


@click.command("list")
@click.option("--deleted", is_flag=True, help="Include soft-deleted sessions.")
@click.pass_context
def session_list(ctx: click.Context, deleted: bool) -> None:
    """List all agent sessions."""
    mgr, _ = get_managers(ctx)
    sessions = mgr.list_sessions(include_deleted=deleted)
    if not sessions:
        click.echo("No sessions found.")
        return

    status_colors: dict[str, str] = {
        "idle": "green",
        "active": "green",
        "working": "yellow",
        "blocked": "red",
        "done": "cyan",
        "error": "red",
        "unreachable": "magenta",
    }

    for s in sessions:
        status_val = s.status or "unknown"
        color = status_colors.get(status_val, "white")
        deleted_marker = click.style("  [DELETED]", fg="bright_black") if s.deleted_at else ""
        click.echo(
            f"  {click.style(s.id[:8], fg='bright_black')}"
            f"  {click.style(s.name, fg='white', bold=True)}"
            f"  [{click.style(status_val, fg=color)}]"
            f"  {click.style(s.agent or '', fg='blue')}"
            f"  {s.cwd or ''}"
            f"{deleted_marker}"
        )


@click.command("create")
@click.option("--name", required=True, help="Unique name for this session.")
@click.option(
    "--repo-path",
    required=True,
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    help="Path to the git repository.",
)
@click.option("--agent", default="claude", show_default=True, help="Agent to launch.")
@click.option("--worktree-branch", default=None, help="Create a git worktree on this branch.")
@click.option("--base-branch", default="main", show_default=True, help="Base branch for the worktree.")
@click.option("--tag", default=None, help="Optional group tag.")
@click.pass_context
def session_create(
    ctx: click.Context,
    name: str,
    repo_path: str,
    agent: str,
    worktree_branch: str | None,
    base_branch: str,
    tag: str | None,
) -> None:
    """Create a new agent session."""
    mgr, _ = get_managers(ctx)
    try:
        session = mgr.create_session(
            name=name,
            repo_path=repo_path,
            agent=agent,
            worktree_branch=worktree_branch,
            base_branch=base_branch,
            tag=tag,
        )
    except Exception as exc:
        click.echo(click.style(f"Error: {exc}", fg="red"), err=True)
        sys.exit(1)

    click.echo(
        click.style("✓", fg="green")
        + f" Session {click.style(session.name, bold=True)}"
        f" created (id={click.style(session.id[:8], fg='bright_black')}"
        f", pane={session.backend_id or 'n/a'})"
    )


@click.command("delete")
@click.argument("session_id")
@click.option("--force", is_flag=True, help="Kill tmux window and remove worktree.")
@click.pass_context
def session_delete(ctx: click.Context, session_id: str, force: bool) -> None:
    """Delete a session (soft-delete unless --force)."""
    mgr, _ = get_managers(ctx)
    ok = mgr.delete_session(session_id, force=force)
    if ok:
        verb = "hard-deleted" if force else "soft-deleted"
        click.echo(click.style("✓", fg="green") + f" Session {session_id[:8]} {verb}.")
    else:
        click.echo(click.style(f"Session '{session_id}' not found.", fg="red"), err=True)
        sys.exit(1)


@click.command("send")
@click.argument("session_id")
@click.argument("text")
@click.option("--no-enter", is_flag=True, help="Do not send an Enter keystroke after the text.")
@click.pass_context
def session_send(ctx: click.Context, session_id: str, text: str, no_enter: bool) -> None:
    """Send text to a session's terminal."""
    mgr, _ = get_managers(ctx)
    ok = mgr.send_text(session_id, text, press_enter=not no_enter)
    if ok:
        click.echo(click.style("✓", fg="green") + f" Sent to session {session_id[:8]}.")
    else:
        click.echo(
            click.style(f"Failed to send — session '{session_id}' not found or has no pane.", fg="red"),
            err=True,
        )
        sys.exit(1)


@click.command("capture")
@click.argument("session_id")
@click.option("--lines", default=100, show_default=True, help="Number of scrollback lines to capture.")
@click.pass_context
def session_capture(ctx: click.Context, session_id: str, lines: int) -> None:
    """Capture terminal output from a session."""
    mgr, _ = get_managers(ctx)
    output = mgr.capture(session_id, lines=lines)
    if output:
        click.echo(output)
    else:
        click.echo(
            click.style(f"No output — session '{session_id}' not found or pane is empty.", fg="yellow"),
            err=True,
        )


@click.command("signal")
@click.argument("session_id")
@click.argument("state", type=click.Choice(["working", "blocked", "done", "idle"]))
@click.pass_context
def session_signal(ctx: click.Context, session_id: str, state: str) -> None:
    """Set the hook state for a session."""
    mgr, _ = get_managers(ctx)
    try:
        mgr.set_hook_state(session_id, state)
        click.echo(click.style("✓", fg="green") + f" Session {session_id[:8]} state → {state}.")
    except ValueError as exc:
        click.echo(click.style(f"Error: {exc}", fg="red"), err=True)
        sys.exit(1)


@click.command("restart")
@click.argument("session_id")
@click.pass_context
def session_restart(ctx: click.Context, session_id: str) -> None:
    """Restart the agent in a session."""
    mgr, _ = get_managers(ctx)
    ok = mgr.restart_session(session_id)
    if ok:
        click.echo(click.style("✓", fg="green") + f" Session {session_id[:8]} restarted.")
    else:
        click.echo(
            click.style(f"Failed to restart session '{session_id}'.", fg="red"),
            err=True,
        )
        sys.exit(1)


@click.command("sync")
@click.argument("remote_url")
@click.option("--token", required=True, help="Authentication token for the remote instance.")
@click.pass_context
def session_sync(ctx: click.Context, remote_url: str, token: str) -> None:
    """Sync session state from a remote Synapse instance."""
    mgr, _ = get_managers(ctx)
    synced = mgr.sync_from_remote(remote_url, token)
    click.echo(
        click.style("✓", fg="green")
        + f" Synced {synced} session(s) from {remote_url}"
    )


@click.command("counter")
@click.option("--prefix", default="session", show_default=True, help="Name prefix.")
@click.pass_context
def session_counter(ctx: click.Context, prefix: str) -> None:
    """Show the next unique session number."""
    mgr, _ = get_managers(ctx)
    num = mgr.get_next_session_number(prefix)
    click.echo(f"  Next session name: {click.style(f'{prefix}-{num}', fg='cyan', bold=True)}")
    click.echo(f"  (from {num-1} existing '{prefix}-*' session(s))")
