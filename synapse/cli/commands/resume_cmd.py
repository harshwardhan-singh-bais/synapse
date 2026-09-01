"""Click command for `synapse resume` — resume a tmux session."""
from __future__ import annotations

import sys

import click

from ...backend.tmux import TmuxBackend
from ...core.config import SynapseConfig, load_agents_toml
from ...db.database import Database
from ...session.manager import SessionManager


@click.command("resume")
@click.argument("session_id")
@click.pass_context
def resume_session(ctx: click.Context, session_id: str) -> None:
    """Resume a tmux session, re-injecting the session_id into the agent.

    SESSION_ID is the ID or name of the session to resume.
    This re-launches the agent command in the existing tmux window,
    injecting the session ID so the agent can resume its prior context.
    """
    config: SynapseConfig = ctx.obj["config"]
    db = Database(config.db_path)
    tmux = TmuxBackend()
    mgr = SessionManager(db, tmux, config)

    session = mgr.get_session(session_id) or mgr._resolve_session(session_id)
    if session is None:
        click.echo(click.style(f"Session '{session_id}' not found.", fg="red"), err=True)
        sys.exit(1)

    # Re-launch with session_id injection
    agent_name = session.agent or config.default_agent
    agent_map = load_agents_toml()
    agent_def = agent_map.get(agent_name)

    cwd = session.cwd or "."
    if agent_def:
        cmd = agent_def.command or agent_name
        # Use resume_args if configured, otherwise fall back to --resume flag
        if agent_def.resume_args:
            for arg in agent_def.resume_args:
                arg = arg.replace("{id}", session.agent_session_id or session.id)
                cmd += " " + arg
        else:
            cmd += f" --resume {session.agent_session_id or session.id}"
    else:
        cmd = f"{agent_name} --resume {session.agent_session_id or session.id}"

    # Kill existing window if it exists
    if session.backend_id and tmux.pane_exists(session.backend_id):
        try:
            tmux.kill_window(session.backend_id)
        except Exception:
            pass

    # Create new window with the resume command
    tmux_session_name = f"synapse-{session.name}"
    window_name = session.id[:8]

    try:
        pane = tmux.new_window(
            session_name=tmux_session_name,
            window_name=window_name,
            cwd=cwd,
            cmd=cmd,
        )
        new_backend_id = pane.pane_id or f"{tmux_session_name}:{window_name}"
    except Exception as exc:
        click.echo(click.style(f"Failed to resume: {exc}", fg="red"), err=True)
        sys.exit(1)

    # Update DB
    now = db.now_ms()
    db.execute(
        "UPDATE sessions SET backend_id=?, status='active', hook_state='idle', updated_at=? WHERE id=?",
        (new_backend_id, now, session.id),
    )

    click.echo(
        click.style("✓", fg="green")
        + f" Session {click.style(session.name, bold=True)} resumed"
        + f" (id={click.style(session.id[:8], fg='bright_black')})"
    )
