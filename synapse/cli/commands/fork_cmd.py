"""Click command for `synapse fork` — fork a session into a child."""
from __future__ import annotations

import sys
import uuid

import click

from ...backend.tmux import TmuxBackend
from ...core.config import SynapseConfig, load_agents_toml
from ...db.database import Database
from ...session.manager import SessionManager


@click.command("fork")
@click.argument("session_id")
@click.option("--name", default=None, help="Name for the forked session.")
@click.pass_context
def fork_session(ctx: click.Context, session_id: str, name: str | None) -> None:
    """Fork a session — create a child session that resumes the parent's conversation.

    SESSION_ID is the ID or name of the parent session.
    """
    config: SynapseConfig = ctx.obj["config"]
    db = Database(config.db_path)
    tmux = TmuxBackend()
    mgr = SessionManager(db, tmux, config)

    parent = mgr.get_session(session_id) or mgr._resolve_session(session_id)
    if parent is None:
        click.echo(click.style(f"Session '{session_id}' not found.", fg="red"), err=True)
        sys.exit(1)

    if not name:
        name = f"{parent.name}-fork"

    now = db.now_ms()
    child_id = str(uuid.uuid4())

    # Determine agent and cwd
    agent_name = parent.agent or config.default_agent
    cwd = parent.cwd or "."
    agent_map = load_agents_toml()
    agent_def = agent_map.get(agent_name)

    # Build fork command (resume parent's session)
    if agent_def:
        cmd = agent_def.command or agent_name
        if hasattr(agent_def, "fork_args") and agent_def.fork_args:
            for arg in agent_def.fork_args:
                arg = arg.replace("{id}", parent.agent_session_id or parent.id)
                cmd += " " + arg
        elif hasattr(agent_def, "resume_args") and agent_def.resume_args:
            for arg in agent_def.resume_args:
                arg = arg.replace("{id}", parent.agent_session_id or parent.id)
                cmd += " " + arg
    else:
        cmd = f"{agent_name} --resume {parent.agent_session_id or parent.id}"

    # Launch in tmux
    tmux_session_name = f"synapse-{name}"
    window_name = child_id[:8]

    try:
        pane = tmux.new_window(
            session_name=tmux_session_name,
            window_name=window_name,
            cwd=cwd,
            cmd=cmd,
        )
        backend_id = pane.pane_id or f"{tmux_session_name}:{window_name}"
    except Exception as exc:
        click.echo(click.style(f"Failed to fork: {exc}", fg="red"), err=True)
        sys.exit(1)

    # Insert child session
    db.execute(
        """
        INSERT INTO sessions (
            id, name, agent, backend_id, backend_type, cwd,
            hook_state, status, parent_session_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'idle', 'active', ?, ?, ?)
        """,
        (child_id, name, agent_name, backend_id, parent.backend_type or "local-tmux",
         cwd, parent.id, now, now),
    )

    click.echo(
        click.style("✓", fg="green")
        + f" Forked {click.style(parent.name, bold=True)} → "
        + f"{click.style(name, bold=True)} "
        + f"(id={click.style(child_id[:8], fg='bright_black')})"
    )
