"""Click commands for `synapse archive` and `synapse reset`."""
from __future__ import annotations

import shutil
import sys
import time

import click

from ...core.config import SynapseConfig
from ...core.paths import DATA_DIR, CONFIG_DIR
from ...db.database import Database


@click.command("archive")
@click.option("--output", default=None, help="Output path for the archive.")
@click.pass_context
def archive_db(ctx: click.Context, output: str | None) -> None:
    """Archive (snapshot) the current database.

    Creates a timestamped copy of the database file.
    """
    config: SynapseConfig = ctx.obj["config"]
    db_path = config.db_path

    if not db_path.exists():
        click.echo(click.style("Database not found.", fg="red"), err=True)
        sys.exit(1)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    if output:
        archive_path = output
    else:
        archive_dir = DATA_DIR / "archives"
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive_path = str(archive_dir / f"synapse_{timestamp}.db")

    try:
        shutil.copy2(str(db_path), archive_path)
        click.echo(click.style("✓", fg="green") + f" Database archived to {archive_path}")
    except Exception as exc:
        click.echo(click.style(f"Error: {exc}", fg="red"), err=True)
        sys.exit(1)


@click.command("reset")
@click.option("--yes", is_flag=True, help="Skip confirmation.")
@click.option("--archive-first", is_flag=True, default=True, help="Archive before resetting.")
@click.pass_context
def reset_all(ctx: click.Context, yes: bool, archive_first: bool) -> None:
    """Clear and archive the database, hooks, and config.

    WARNING: This will delete all sessions, messages, and run history.
    """
    config: SynapseConfig = ctx.obj["config"]

    if not yes:
        click.echo(click.style("⚠️  WARNING: This will delete all Synapse data!", fg="red", bold=True))
        click.echo("  This includes: sessions, messages, automations, tasks, runs.")
        if not click.confirm("  Are you sure you want to continue?"):
            click.echo("  Cancelled.")
            return

    # Archive first
    if archive_first:
        try:
            ctx.invoke(archive_db, output=None)
        except Exception:
            pass

    # Remove database
    db_path = config.db_path
    if db_path.exists():
        db_path.unlink()
        click.echo(f"  Removed database: {db_path}")

    # Remove worktrees
    from ...core.paths import WORKTREES_DIR
    if WORKTREES_DIR.exists():
        shutil.rmtree(WORKTREES_DIR, ignore_errors=True)
        click.echo(f"  Removed worktrees: {WORKTREES_DIR}")

    # Remove runs
    from ...core.paths import RUNS_DIR
    if RUNS_DIR.exists():
        shutil.rmtree(RUNS_DIR, ignore_errors=True)
        click.echo(f"  Removed runs: {RUNS_DIR}")

    click.echo(click.style("✓", fg="green") + " Reset complete. Restart synapse to reinitialize.")
