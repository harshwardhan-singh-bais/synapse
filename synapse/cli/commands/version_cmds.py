"""Click commands for `synapse version` and `synapse update`."""
from __future__ import annotations

import os
import sys

import click


SYNAPSE_VERSION = "0.1.0"


@click.command("version")
@click.option("--check", is_flag=True, help="Check for a newer version on GitHub.")
@click.pass_context
def version_cmd(ctx: click.Context, check: bool) -> None:
    """Show Synapse version."""
    click.echo(f"  synapse {SYNAPSE_VERSION}")

    if check:
        click.echo("  Checking for updates...")
        try:
            import httpx
            resp = httpx.get(
                "https://api.github.com/repos/synapse-agent/synapse/releases/latest",
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                latest = data.get("tag_name", "unknown")
                if latest.lstrip("v") != SYNAPSE_VERSION:
                    click.echo(f"  New version available: {latest}")
                    click.echo(f"  Run `synapse update` to upgrade.")
                else:
                    click.echo("  You're up to date!")
            else:
                click.echo("  Could not check for updates.")
        except Exception as exc:
            click.echo(f"  Update check failed: {exc}")


@click.command("update")
@click.option("--force", is_flag=True, help="Force update even if already on latest.")
@click.pass_context
def update_cmd(ctx: click.Context, force: bool) -> None:
    """Self-update Synapse to the latest version.

    Downloads and installs the latest release from PyPI or GitHub.
    """
    import subprocess
    import shutil
    import sys as _sys

    click.echo("  Checking for updates...")

    # Check latest version from GitHub
    latest_version: str | None = None
    try:
        import httpx
        resp = httpx.get(
            "https://api.github.com/repos/synapse-agent/synapse/releases/latest",
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            latest_version = data.get("tag_name", "").lstrip("v")
    except Exception:
        pass

    if latest_version and latest_version == SYNAPSE_VERSION and not force:
        click.echo(f"  Already on latest version ({SYNAPSE_VERSION}).")
        return

    if latest_version:
        click.echo(f"  Updating from {SYNAPSE_VERSION} to {latest_version}...")
    else:
        click.echo(f"  Updating to latest version...")

    # Try pip install first
    pip = shutil.which("pip") or shutil.which("pip3")
    if pip:
        try:
            result = subprocess.run(
                [pip, "install", "--upgrade", "synapse"],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode == 0:
                click.echo(click.style("  ✓ Update complete!", fg="green"))
                click.echo(f"  Version: {latest_version or 'latest'}")
                return
            else:
                click.echo(click.style(f"  pip install failed: {result.stderr[:200]}", fg="yellow"))
        except Exception as exc:
            click.echo(click.style(f"  pip install failed: {exc}", fg="yellow"))
    else:
        click.echo(click.style("  pip not found. Install from source:", fg="yellow"))
        click.echo("    pip install -e .")
        return

    # Fallback: suggest manual install
    click.echo(click.style("  Auto-update failed. Try manually:", fg="yellow"))
    click.echo("    pip install --upgrade synapse")
    click.echo("    # or from source:")
    click.echo("    git pull && pip install -e .")


@click.command("name")
@click.argument("session_id", required=False)
@click.pass_context
def name_export(ctx: click.Context, session_id: str | None) -> None:
    """Export or show the session instance name as an env var.

    If SESSION_ID is provided, shows the instance name for that session.
    Without an argument, exports SYNAPSE_INSTANCE_NAME for the current shell.
    """
    if session_id:
        # Show the instance name for a session
        from ..core.config import SynapseConfig
        from ..db.database import Database

        config: SynapseConfig = ctx.obj["config"]
        db = Database(config.db_path)
        row = db.fetchone(
            "SELECT name FROM sessions WHERE id LIKE ? AND deleted_at IS NULL",
            (f"{session_id}%",),
        )
        if row:
            click.echo(row["name"])
        else:
            click.echo(click.style(f"Session '{session_id}' not found.", fg="red"), err=True)
            sys.exit(1)
    else:
        # Export for current shell
        click.echo('export SYNAPSE_INSTANCE_NAME="synapse-$$"')
        click.echo("  # Add this to your shell profile to auto-export.")
        click.echo("  # Or run: eval $(synapse name)")
