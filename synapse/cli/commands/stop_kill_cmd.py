"""Click commands for `synapse stop` and `synapse kill`."""
from __future__ import annotations

import sys

import click

from ...backend.tmux import TmuxBackend
from ...core.config import SynapseConfig
from ...db.database import Database
from ...session.manager import SessionManager


@click.command("stop")
@click.argument("session_id")
@click.pass_context
def stop_session(ctx: click.Context, session_id: str) -> None:
    """Stop (gracefully) a running session.

    Sends SIGTERM to the agent process and waits for it to exit.
    """
    config: SynapseConfig = ctx.obj["config"]
    db = Database(config.db_path)
    tmux = TmuxBackend()
    mgr = SessionManager(db, tmux, config)

    session = mgr.get_session(session_id) or mgr._resolve_session(session_id)
    if session is None:
        click.echo(click.style(f"Session '{session_id}' not found.", fg="red"), err=True)
        sys.exit(1)

    if session.pid:
        import os
        import signal
        try:
            os.kill(session.pid, signal.SIGTERM)
            click.echo(click.style("✓", fg="green") + f" Sent SIGTERM to session {session.name}.")
        except ProcessLookupError:
            click.echo(click.style("Process already stopped.", fg="yellow"))
        except PermissionError:
            click.echo(click.style("Permission denied.", fg="red"), err=True)
            sys.exit(1)
    else:
        click.echo(click.style("No PID recorded for this session.", fg="yellow"))

    # Update status
    now = db.now_ms()
    db.execute(
        "UPDATE sessions SET hook_state='done', hook_state_at=?, status='done', updated_at=? WHERE id=?",
        (now, now, session.id),
    )


@click.command("kill")
@click.argument("session_id")
@click.option("--force", is_flag=True, help="Force kill (SIGKILL).")
@click.pass_context
def kill_session(ctx: click.Context, session_id: str, force: bool) -> None:
    """Kill a session and optionally close its terminal pane.

    By default sends SIGTERM then SIGKILL after 5 seconds.
    With --force sends SIGKILL immediately.
    """
    config: SynapseConfig = ctx.obj["config"]
    db = Database(config.db_path)
    tmux = TmuxBackend()
    mgr = SessionManager(db, tmux, config)

    session = mgr.get_session(session_id) or mgr._resolve_session(session_id)
    if session is None:
        click.echo(click.style(f"Session '{session_id}' not found.", fg="red"), err=True)
        sys.exit(1)

    if session.pid:
        import os
        import signal
        try:
            if force:
                os.kill(session.pid, signal.SIGKILL)
                click.echo(click.style("✓", fg="green") + f" SIGKILL sent to session {session.name}.")
            else:
                os.kill(session.pid, signal.SIGTERM)
                import time
                time.sleep(2)
                try:
                    os.kill(session.pid, 0)  # Check if still alive
                    os.kill(session.pid, signal.SIGKILL)
                    click.echo(click.style("✓", fg="green") + f" Force-killed session {session.name}.")
                except ProcessLookupError:
                    click.echo(click.style("✓", fg="green") + f" Session {session.name} stopped.")
        except ProcessLookupError:
            click.echo(click.style("Process already stopped.", fg="yellow"))
    else:
        click.echo(click.style("No PID recorded.", fg="yellow"))

    # Kill tmux window
    if session.backend_id:
        try:
            tmux.kill_window(session.backend_id)
        except Exception:
            pass

    # Update DB
    now = db.now_ms()
    db.execute(
        "UPDATE sessions SET hook_state='done', status='done', updated_at=? WHERE id=?",
        (now, session.id),
    )
