"""Click command for `synapse listen` — block waiting for messages."""
from __future__ import annotations

import json
import sys
import time

import click

from ...core.config import SynapseConfig
from ...db.database import Database
from ...messaging.messenger import Messenger


@click.command("listen")
@click.argument("session_id")
@click.option("--timeout", default=300, show_default=True, help="Max seconds to wait.")
@click.option("--poll", default=1.0, show_default=True, help="Poll interval in seconds.")
@click.pass_context
def listen_session(ctx: click.Context, session_id: str, timeout: int, poll: float) -> None:
    """Block waiting for a message addressed to a session.

    SESSION_ID is the session to listen for messages on.
    Exits when a message arrives or timeout is reached.
    """
    config: SynapseConfig = ctx.obj["config"]
    db = Database(config.db_path)
    messenger = Messenger(db)

    click.echo(f"  Listening for messages to {session_id[:8]}... (timeout={timeout}s)")

    deadline = time.time() + timeout
    try:
        while time.time() < deadline:
            messages = messenger.inbox(session_id, limit=1)
            if messages:
                msg = messages[0]
                # Output the message
                click.echo(f"\n  {click.style('📨 Message received!', fg='green', bold=True)}")
                click.echo(f"  From:   {msg.from_session_id or 'system'}")
                click.echo(f"  Kind:   {msg.kind or 'chat'}")
                click.echo(f"  Body:   {msg.body or ''}")
                if msg.thread_id:
                    click.echo(f"  Thread: {msg.thread_id}")
                # Claim it
                messenger.claim(session_id, limit=1)
                sys.exit(0)
            time.sleep(poll)
    except KeyboardInterrupt:
        click.echo("\n  Stopped listening.")
        sys.exit(0)

    click.echo(click.style("  Timeout reached — no messages received.", fg="yellow"))
    sys.exit(0)
