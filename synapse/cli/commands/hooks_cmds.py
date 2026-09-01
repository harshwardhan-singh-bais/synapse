"""Click commands for `synapse hooks`."""
from __future__ import annotations

import sys

import click

from ...hooks.registry import HookDispatcher, HookInstaller


@click.group("hooks")
def hooks_group() -> None:
    """Install, remove, and verify agent hooks for inter-agent messaging."""
    pass


@hooks_group.command("install")
@click.option("--tool", default="all", help="Tool to install hooks for (claude/gemini/codex/cursor/all).")
@click.pass_context
def hooks_install(ctx: click.Context, tool: str) -> None:
    """Install Synapse hooks into agent config files."""
    installer = HookInstaller()

    if tool == "all":
        results = installer.install_all_hooks()
        for t, ok in results.items():
            status = click.style("✓", fg="green") if ok else click.style("✗", fg="red")
            click.echo(f"  {status} {t}")
    elif tool == "claude":
        ok = installer.install_claude_hooks()
        _report("claude", ok)
    elif tool == "gemini":
        ok = installer.install_gemini_hooks()
        _report("gemini", ok)
    elif tool == "codex":
        ok = installer.install_codex_hooks()
        _report("codex", ok)
    elif tool == "cursor":
        ok = installer.install_cursor_hooks()
        _report("cursor", ok)
    else:
        click.echo(click.style(f"Unknown tool: {tool}", fg="red"), err=True)
        sys.exit(1)


@hooks_group.command("remove")
@click.option("--tool", default="all", help="Tool to remove hooks from.")
@click.pass_context
def hooks_remove(ctx: click.Context, tool: str) -> None:
    """Remove Synapse hooks from agent config files."""
    installer = HookInstaller()

    if tool == "all":
        results = installer.remove_all_hooks()
        for t, ok in results.items():
            status = click.style("✓", fg="green") if ok else click.style("✗", fg="red")
            click.echo(f"  {status} {t}")
    elif tool == "claude":
        ok = installer.remove_claude_hooks()
        _report("claude", ok)
    else:
        click.echo(f"  Removal for {tool} not yet implemented.")


@hooks_group.command("verify")
@click.option("--tool", default="all", help="Tool to verify hooks for.")
@click.pass_context
def hooks_verify(ctx: click.Context, tool: str) -> None:
    """Verify that Synapse hooks are correctly installed."""
    installer = HookInstaller()

    if tool == "all":
        for t in ["claude", "gemini", "codex", "cursor"]:
            ok = installer.verify_claude_hooks() if t == "claude" else False
            status = click.style("✓", fg="green") if ok else click.style("✗", fg="red")
            click.echo(f"  {status} {t}")
    elif tool == "claude":
        ok = installer.verify_claude_hooks()
        _report("claude", ok)
    else:
        click.echo(f"  Verification for {tool} not yet implemented.")


@hooks_group.command("list")
@click.pass_context
def hooks_list(ctx: click.Context) -> None:
    """List all known hook events and their status."""
    from ...hooks.registry import HookEvent
    click.echo("  Known hook events:\n")
    for event in HookEvent:
        click.echo(f"    {event.value}")
    click.echo()


def _report(tool: str, ok: bool) -> None:
    status = click.style("✓ installed", fg="green") if ok else click.style("✗ failed", fg="red")
    click.echo(f"  {tool}: {status}")
