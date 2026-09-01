"""Click commands for `synapse extension`."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from ...core.config import SynapseConfig
from ...core.paths import CONFIG_DIR


EXTENSIONS_DIR = CONFIG_DIR / "extensions"


@click.group("extension")
def extension_group() -> None:
    """Manage Synapse extensions."""
    pass


@extension_group.command("list")
@click.pass_context
def extension_list(ctx: click.Context) -> None:
    """List installed extensions."""
    if not EXTENSIONS_DIR.exists():
        click.echo("  No extensions installed.")
        return

    extensions = []
    for entry in sorted(EXTENSIONS_DIR.iterdir()):
        if entry.is_dir():
            manifest = entry / "manifest.json"
            if manifest.exists():
                try:
                    data = json.loads(manifest.read_text(encoding="utf-8"))
                    extensions.append(data)
                except (json.JSONDecodeError, OSError):
                    extensions.append({"name": entry.name, "version": "?"})
            else:
                extensions.append({"name": entry.name, "version": "?"})

    if not extensions:
        click.echo("  No extensions installed.")
        return

    click.echo(f"\n  {len(extensions)} extension(s):\n")
    for ext in extensions:
        name = ext.get("name", "?")
        version = ext.get("version", "?")
        desc = ext.get("description", "")[:60]
        click.echo(f"    {click.style(name, fg='cyan')} v{version}")
        if desc:
            click.echo(f"      {desc}")


@extension_group.command("activate")
@click.argument("name")
@click.pass_context
def extension_activate(ctx: click.Context, name: str) -> None:
    """Activate an extension."""
    ext_dir = EXTENSIONS_DIR / name
    if not ext_dir.exists():
        click.echo(click.style(f"Extension '{name}' not found.", fg="red"), err=True)
        sys.exit(1)

    # Write enabled marker
    enabled_file = ext_dir / ".enabled"
    enabled_file.write_text("1", encoding="utf-8")
    click.echo(click.style("✓", fg="green") + f" Extension '{name}' activated.")


@extension_group.command("deactivate")
@click.argument("name")
@click.pass_context
def extension_deactivate(ctx: click.Context, name: str) -> None:
    """Deactivate an extension."""
    ext_dir = EXTENSIONS_DIR / name
    if not ext_dir.exists():
        click.echo(click.style(f"Extension '{name}' not found.", fg="red"), err=True)
        sys.exit(1)

    enabled_file = ext_dir / ".enabled"
    if enabled_file.exists():
        enabled_file.unlink()
    click.echo(click.style("✓", fg="green") + f" Extension '{name}' deactivated.")
