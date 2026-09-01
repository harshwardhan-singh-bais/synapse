"""Click commands for `synapse bundle` and `synapse term`."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from ...core.config import SynapseConfig
from ...db.database import Database


@click.command("bundle")
@click.argument("session_id")
@click.option("--title", default=None, help="Bundle title.")
@click.option("--description", default=None, help="Bundle description.")
@click.option("--output", default=None, help="Output file path.")
@click.pass_context
def bundle_context(ctx: click.Context, session_id: str, title: str | None, description: str | None, output: str | None) -> None:
    """Prepare a handoff context bundle for a session.

    Collects recent messages, events, and session info into a single JSON bundle
    that can be passed to another agent or tool.
    """
    config: SynapseConfig = ctx.obj["config"]
    db = Database(config.db_path)

    # Get session info
    row = db.fetchone("SELECT * FROM sessions WHERE id LIKE ? AND deleted_at IS NULL", (f"{session_id}%",))
    if not row:
        click.echo(click.style(f"Session '{session_id}' not found.", fg="red"), err=True)
        sys.exit(1)

    session = dict(row)

    # Get recent messages
    messages = db.fetchall(
        "SELECT * FROM messages WHERE (to_session_id = ? OR from_session_id = ?) ORDER BY created_at DESC LIMIT 50",
        (session["id"], session["id"]),
    )

    # Get recent events
    events = db.fetchall(
        "SELECT * FROM events WHERE session_id = ? ORDER BY timestamp DESC LIMIT 100",
        (session["id"],),
    )

    bundle = {
        "title": title or f"Bundle for {session['name']}",
        "description": description or "",
        "session": {
            "id": session["id"],
            "name": session["name"],
            "agent": session["agent"],
            "cwd": session["cwd"],
            "status": session["status"],
        },
        "messages": [
            {
                "from": m["from_session_id"],
                "to": m["to_session_id"],
                "kind": m["kind"],
                "body": m["body"],
                "ts": m["created_at"],
            }
            for m in messages
        ],
        "events": [
            {
                "type": e["type"],
                "data": e["data"],
                "ts": e["timestamp"],
            }
            for e in events
        ],
    }

    output_json = json.dumps(bundle, indent=2, default=str)

    if output:
        Path(output).write_text(output_json, encoding="utf-8")
        click.echo(click.style("✓", fg="green") + f" Bundle written to {output}")
    else:
        click.echo(output_json)


@click.command("term")
@click.argument("session_id")
@click.option("--lines", default=50, help="Number of lines to capture.")
@click.option("--ansi", is_flag=True, help="Include ANSI escape codes.")
@click.pass_context
def term_view(ctx: click.Context, session_id: str, lines: int, ansi: bool) -> None:
    """View terminal output from a session.

    Captures the last N lines from the session's tmux pane.
    """
    from ...backend.tmux import TmuxBackend
    from ...session.manager import SessionManager

    config: SynapseConfig = ctx.obj["config"]
    db = Database(config.db_path)
    tmux = TmuxBackend()
    mgr = SessionManager(db, tmux, config)

    output = mgr.capture(session_id, lines=lines)
    if output:
        click.echo(output)
    else:
        click.echo(click.style(f"No output from session '{session_id}'.", fg="yellow"))
