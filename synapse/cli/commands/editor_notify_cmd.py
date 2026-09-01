"""Click commands for `synapse editor` and `synapse notify`."""
from __future__ import annotations

import os
import sys

import click

from ...core.config import SynapseConfig
from ...core.paths import CONFIG_DIR


@click.group("editor")
def editor_group() -> None:
    """Get or set the default editor for Synapse."""
    pass


@editor_group.command("get")
@click.pass_context
def editor_get(ctx: click.Context) -> None:
    """Show the current editor setting."""
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "not set"
    click.echo(f"  Editor: {editor}")


@editor_group.command("set")
@click.argument("editor_cmd")
@click.pass_context
def editor_set(ctx: click.Context, editor_cmd: str) -> None:
    """Set the default editor (writes to ~/.config/synapse/config.toml)."""
    config_path = CONFIG_DIR / "config.toml"

    # Read existing config
    content = ""
    if config_path.exists():
        content = config_path.read_text(encoding="utf-8")

    # Add or update editor setting
    if "[editor]" in content:
        # Update existing
        lines = content.split("\n")
        in_editor = False
        new_lines = []
        for line in lines:
            if line.strip() == "[editor]":
                in_editor = True
                new_lines.append(line)
            elif in_editor and line.strip().startswith("command"):
                new_lines.append(f'command = "{editor_cmd}"')
                in_editor = False
            elif in_editor and line.strip().startswith("["):
                new_lines.append(f'command = "{editor_cmd}"')
                new_lines.append(line)
                in_editor = False
            else:
                new_lines.append(line)
        if in_editor:
            new_lines.append(f'command = "{editor_cmd}"')
        content = "\n".join(new_lines)
    else:
        content += f'\n[editor]\ncommand = "{editor_cmd}"\n'

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(content, encoding="utf-8")
    click.echo(click.style("✓", fg="green") + f" Editor set to: {editor_cmd}")


@click.command("notify")
@click.option("--test", is_flag=True, help="Send a test notification.")
@click.pass_context
def notify_cmd(ctx: click.Context, test: bool) -> None:
    """Diagnose OS notification support."""
    from ...notifications.notifier import send_notification, platform

    system = platform.system()
    click.echo(f"  Platform: {system}")

    if system == "Linux":
        # Check for notify-send
        import shutil
        has_notify = shutil.which("notify-send") is not None
        click.echo(f"  notify-send: {'✓ found' if has_notify else '✗ not found'}")
    elif system == "Darwin":
        click.echo(f"  osascript: ✓ (always available on macOS)")
    elif system == "Windows":
        click.echo(f"  PowerShell: ✓ (always available on Windows)")

    if test:
        click.echo("  Sending test notification...")
        ok = send_notification("Synapse Test", "If you see this, notifications work!")
        if ok:
            click.echo(click.style("  ✓ Notification sent!", fg="green"))
        else:
            click.echo(click.style("  ✗ Notification failed.", fg="red"))
