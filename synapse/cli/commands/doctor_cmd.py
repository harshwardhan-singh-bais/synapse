"""Click command for `synapse doctor` — session health diagnostics."""
from __future__ import annotations

import click

from ...backend.tmux import TmuxBackend
from ...core.config import SynapseConfig
from ...db.database import Database
from ...session.manager import SessionManager


@click.command("doctor")
@click.argument("session_id", required=False)
@click.pass_context
def session_doctor(ctx: click.Context, session_id: str | None) -> None:
    """Diagnose session health issues.

    If SESSION_ID is provided, checks that specific session.
    Without an argument, checks all active sessions.
    """
    config: SynapseConfig = ctx.obj["config"]
    db = Database(config.db_path)
    tmux = TmuxBackend()
    mgr = SessionManager(db, tmux, config)

    if session_id:
        sessions = [mgr.get_session(session_id) or mgr._resolve_session(session_id)]
        sessions = [s for s in sessions if s is not None]
    else:
        sessions = mgr.list_sessions()

    if not sessions:
        click.echo("  No sessions to check.")
        return

    issues = 0
    for session in sessions:
        name = session.name
        sid = session.id[:8]
        click.echo(f"\n  Checking {click.style(name, bold=True)} ({sid})...")

        # Check tmux pane
        if session.backend_id:
            if tmux.pane_exists(session.backend_id):
                click.echo(f"    ✓ tmux pane exists ({session.backend_id})")
            else:
                click.echo(f"    ✗ tmux pane MISSING ({session.backend_id})")
                issues += 1

        # Check hook state
        if session.hook_state:
            click.echo(f"    ✓ hook_state = {session.hook_state}")
        else:
            click.echo(f"    ⚠ hook_state not set")

        # Check cwd
        if session.cwd:
            from pathlib import Path
            if Path(session.cwd).exists():
                click.echo(f"    ✓ cwd exists ({session.cwd})")
            else:
                click.echo(f"    ✗ cwd MISSING ({session.cwd})")
                issues += 1
        else:
            click.echo(f"    ⚠ cwd not set")

        # Check agent
        if session.agent:
            import shutil
            if shutil.which(session.agent):
                click.echo(f"    ✓ agent binary found ({session.agent})")
            else:
                click.echo(f"    ⚠ agent binary not in PATH ({session.agent})")
        else:
            click.echo(f"    ⚠ agent not set")

    click.echo(f"\n  {'✓ All checks passed' if issues == 0 else f'✗ {issues} issue(s) found'}")
