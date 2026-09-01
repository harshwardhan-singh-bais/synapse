"""Click command for `synapse start` — register an external process with the message bus.

This is the hcom-style escape hatch: any external tool without native hooks
can join the Synapse mailbox by registering itself.
"""
from __future__ import annotations

import sys
import uuid

import click

from ...backend.tmux import TmuxBackend
from ...core.config import SynapseConfig
from ...db.database import Database
from ...session.manager import SessionManager


@click.command("start")
@click.argument("name", required=False)
@click.option("--agent", default="generic", show_default=True, help="Agent type label.")
@click.option("--cwd", default=".", help="Working directory to report.")
@click.option("--tag", default=None, help="Optional group tag.")
@click.pass_context
def start_process(
    ctx: click.Context,
    name: str | None,
    agent: str,
    cwd: str,
    tag: str | None,
) -> None:
    """Register an external process with the Synapse message bus.

    NAME is a unique identifier for this process (auto-generated if omitted).

    This lets tools without native Synapse hooks join the inter-session
    mailbox. Once registered, the process can send/receive messages via
    `synapse message send/inbox/claim`.
    """
    config: SynapseConfig = ctx.obj["config"]
    db = Database(config.db_path)

    if name is None:
        name = f"ext-{uuid.uuid4().hex[:8]}"

    now = db.now_ms()
    session_id = str(uuid.uuid4())

    # Check for duplicate name
    existing = db.fetchone(
        "SELECT id FROM sessions WHERE name = ? AND deleted_at IS NULL",
        (name,),
    )
    if existing:
        click.echo(
            click.style(f"Error: Session name '{name}' already exists.", fg="red"),
            err=True,
        )
        sys.exit(1)

    db.execute(
        """
        INSERT INTO sessions (
            id, name, agent, status, hook_state, cwd, tag,
            created_at, updated_at
        ) VALUES (?, ?, ?, 'active', 'idle', ?, ?, ?, ?)
        """,
        (session_id, name, agent, cwd, tag, now, now),
    )

    click.echo(
        click.style("✓", fg="green")
        + f" Process {click.style(name, bold=True)} registered"
        f" (id={click.style(session_id[:8], fg='bright_black')})."
    )
    click.echo(
        f"\n  Use these commands to interact:\n"
        f"    synapse message send --to {session_id[:8]} --body 'hello'\n"
        f"    synapse message inbox {session_id[:8]}\n"
        f"    synapse message claim {session_id[:8]}\n"
        f"    synapse session send {session_id[:8]} 'text to inject'\n"
    )
