"""Synapse CLI — top-level Click group with all subcommands."""
from __future__ import annotations

import sys
import os

# Fix Windows console encoding for emoji in --help output
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import click

from ..core.config import SynapseConfig
from ..core.paths import CONFIG_DIR, ensure_dirs
from ..defaults import install_defaults

# ── Session commands ──────────────────────────────────────────────────────────
from .commands.session_cmds import (
    session_capture,
    session_counter,
    session_create,
    session_delete,
    session_list,
    session_restart,
    session_send,
    session_signal,
    session_sync,
)

# ── Message commands ──────────────────────────────────────────────────────────
from .commands.message_cmds import (
    message_claim,
    message_collisions,
    message_inbox,
    message_reply,
    message_send,
    message_subscribe,
    message_subscriptions,
    message_unsubscribe,
)

# ── Orchestrate commands ──────────────────────────────────────────────────────
from .commands.orchestrate_cmds import (
    orchestrate_adaptive,
    orchestrate_fix_from,
    orchestrate_goal,
    orchestrate_improve,
    orchestrate_resume,
    orchestrate_test,
)

# ── Automation commands ───────────────────────────────────────────────────────
from .commands.automation_cmds import (
    automation_create,
    automation_delete,
    automation_edit,
    automation_history,
    automation_list,
    automation_trigger,
)

# ── Task commands ─────────────────────────────────────────────────────────────
from .commands.task_cmds import (
    task_create,
    task_delete,
    task_edit,
    task_list,
    task_prompt,
    task_run,
    task_session_name,
    task_show,
)

# ── Relay commands ────────────────────────────────────────────────────────────
from .commands.relay_cmds import (
    relay_connect,
    relay_new,
    relay_off,
    relay_on,
    relay_status,
)

# ── Start command (external process registration) ────────────────────────────
from .commands.start_cmd import start_process


# ──────────────────────────────────────────────────────────────────────────────
# Root group
# ──────────────────────────────────────────────────────────────────────────────


@click.group()
@click.version_option(package_name="synapse")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """⚡ Synapse — unified coding-agent orchestration platform."""
    ensure_dirs()
    install_defaults(CONFIG_DIR)
    ctx.ensure_object(dict)
    ctx.obj["config"] = SynapseConfig.load()


# ──────────────────────────────────────────────────────────────────────────────
# Status dashboard
# ──────────────────────────────────────────────────────────────────────────────


@cli.command("status")
@click.pass_context
def show_status(ctx: click.Context) -> None:
    """Show current Synapse status (sessions, runs, mailbox, relay)."""
    from rich.console import Console
    from rich.table import Table
    from rich import box as rbox
    from rich.text import Text

    from ..db.database import Database
    from ..relay.mqtt_relay import RelayConfig

    config: SynapseConfig = ctx.obj["config"]
    db = Database(config.db_path)
    console = Console()

    console.print()
    console.print(
        "  [bold cyan]⚡ Synapse[/bold cyan]  [dim]unified coding-agent orchestration[/dim]"
    )
    console.print()

    # ── Sessions ─────────────────────────────────────────────────
    session_rows = db.fetchall(
        "SELECT * FROM sessions WHERE deleted_at IS NULL ORDER BY created_at DESC LIMIT 20"
    )
    sessions_table = Table(
        box=rbox.SIMPLE,
        show_header=True,
        header_style="bold",
        padding=(0, 1),
    )
    sessions_table.add_column("ID", style="dim", no_wrap=True)
    sessions_table.add_column("Name", style="bold white")
    sessions_table.add_column("Status")
    sessions_table.add_column("Agent", style="blue")
    sessions_table.add_column("CWD", style="dim")

    _status_style: dict[str, str] = {
        "idle":        "green",
        "active":      "green",
        "working":     "yellow",
        "blocked":     "red",
        "done":        "cyan",
        "error":       "red bold",
        "unreachable": "magenta",
    }

    for row in session_rows:
        status_val = row["status"] or "unknown"
        style = _status_style.get(status_val, "white")
        sessions_table.add_row(
            (row["id"] or "")[:8],
            row["name"] or "",
            Text(status_val, style=style),
            row["agent"] or "",
            (row["cwd"] or "")[-40:],
        )

    active_count = sum(1 for r in session_rows if r["status"] in ("idle", "active", "working", "blocked"))
    console.print(f"  [bold]Sessions[/bold]  ({active_count} active / {len(session_rows)} total)")
    if session_rows:
        console.print(sessions_table)
    else:
        console.print("  [dim]No sessions. Run `synapse session create` to start one.[/dim]\n")

    # ── Runs ─────────────────────────────────────────────────────
    run_rows = db.fetchall(
        "SELECT * FROM runs WHERE status IN ('running','paused') ORDER BY created_at DESC LIMIT 5"
    )
    if run_rows:
        runs_table = Table(box=rbox.SIMPLE, show_header=True, header_style="bold", padding=(0, 1))
        runs_table.add_column("ID", style="dim")
        runs_table.add_column("Mode", style="cyan")
        runs_table.add_column("Status")
        runs_table.add_column("Goal")
        for row in run_rows:
            runs_table.add_row(
                (row["id"] or "")[:8],
                row["mode"] or "",
                row["status"] or "",
                (row["goal"] or "")[:60],
            )
        console.print(f"  [bold]Active Runs[/bold]  ({len(run_rows)})")
        console.print(runs_table)

    # ── Mailbox ───────────────────────────────────────────────────
    unread_row = db.fetchone(
        "SELECT COUNT(*) as cnt FROM messages WHERE claimed_at IS NULL"
    )
    unread = unread_row["cnt"] if unread_row else 0
    if unread:
        console.print(
            f"  [bold]Mailbox[/bold]  [yellow]{unread} unread message(s)[/yellow]"
            "  — run `synapse message inbox <session_id>` to view\n"
        )
    else:
        console.print("  [bold]Mailbox[/bold]  [dim]No unread messages[/dim]\n")

    # ── Tasks ─────────────────────────────────────────────────────
    task_rows = db.fetchall(
        "SELECT status, COUNT(*) as cnt FROM tasks WHERE deleted_at IS NULL GROUP BY status"
    )
    if task_rows:
        task_counts = {r["status"]: r["cnt"] for r in task_rows}
        todo = task_counts.get("todo", 0)
        wip = task_counts.get("in_progress", 0)
        done = task_counts.get("done", 0)
        console.print(
            f"  [bold]Tasks[/bold]"
            f"  [white]{todo} todo[/white]"
            f"  [yellow]{wip} in-progress[/yellow]"
            f"  [green]{done} done[/green]\n"
        )

    # ── Relay ─────────────────────────────────────────────────────
    relay_cfg = RelayConfig(db)
    relay_id = relay_cfg.get("relay_id") or "(none)"
    relay_url = relay_cfg.url or "(not configured)"
    if relay_cfg.enabled:
        console.print(
            f"  [bold]Relay[/bold]  [green]enabled[/green]"
            f"  id={relay_id[:8]}  url={relay_url}\n"
        )
    else:
        console.print("  [bold]Relay[/bold]  [dim]disabled[/dim]\n")


# ──────────────────────────────────────────────────────────────────────────────
# TUI launcher
# ──────────────────────────────────────────────────────────────────────────────


@cli.command()
@click.pass_context
def tui(ctx: click.Context) -> None:
    """Launch the Synapse TUI (interactive terminal dashboard)."""
    from ..tui.app import launch_tui
    launch_tui(ctx.obj["config"])


# ──────────────────────────────────────────────────────────────────────────────
# session
# ──────────────────────────────────────────────────────────────────────────────


@cli.group()
def session() -> None:
    """Manage agent sessions."""


session.add_command(session_list)
session.add_command(session_create)
session.add_command(session_delete)
session.add_command(session_send)
session.add_command(session_capture)
session.add_command(session_signal)
session.add_command(session_restart)
session.add_command(session_sync)
session.add_command(session_counter)

from .commands.doctor_cmd import session_doctor
session.add_command(session_doctor)


@session.command("get")
@click.argument("session_id")
@click.pass_context
def session_get(ctx: click.Context, session_id: str) -> None:
    """Show details for a single session."""
    from ..db.database import Database
    from ..backend.tmux import TmuxBackend
    from ..session.manager import SessionManager

    config: SynapseConfig = ctx.obj["config"]
    db = Database(config.db_path)
    mgr = SessionManager(db, TmuxBackend(), config)

    session_obj = mgr.get_session(session_id) or mgr._resolve_session(session_id)
    if session_obj is None:
        click.echo(click.style(f"Session '{session_id}' not found.", fg="red"), err=True)
        raise SystemExit(1)

    click.echo(f"  id:           {session_obj.id}")
    click.echo(f"  name:         {session_obj.name}")
    click.echo(f"  agent:        {session_obj.agent or ''}")
    click.echo(f"  status:       {session_obj.status or ''}")
    click.echo(f"  hook_state:   {session_obj.hook_state or ''}")
    click.echo(f"  backend_id:   {session_obj.backend_id or ''}")
    click.echo(f"  backend_type: {session_obj.backend_type or ''}")
    click.echo(f"  cwd:          {session_obj.cwd or ''}")
    click.echo(f"  tag:          {session_obj.tag or ''}")
    click.echo(f"  created_at:   {session_obj.created_at}")
    click.echo(f"  parent:       {session_obj.parent_session_id or ''}")


# ──────────────────────────────────────────────────────────────────────────────
# message
# ──────────────────────────────────────────────────────────────────────────────


@cli.group()
def message() -> None:
    """Send and receive inter-agent messages."""


message.add_command(message_send)
message.add_command(message_inbox)
message.add_command(message_claim)
message.add_command(message_reply)
message.add_command(message_subscribe)
message.add_command(message_unsubscribe)
message.add_command(message_subscriptions)
message.add_command(message_collisions)


# ──────────────────────────────────────────────────────────────────────────────
# automation
# ──────────────────────────────────────────────────────────────────────────────


@cli.group()
def automation() -> None:
    """Manage scheduled automations."""


automation.add_command(automation_list)
automation.add_command(automation_create)
automation.add_command(automation_edit)
automation.add_command(automation_delete)
automation.add_command(automation_trigger)
automation.add_command(automation_history)


# ──────────────────────────────────────────────────────────────────────────────
# task
# ──────────────────────────────────────────────────────────────────────────────


@cli.group()
def task() -> None:
    """Manage tasks."""


task.add_command(task_list)
task.add_command(task_show)
task.add_command(task_create)
task.add_command(task_edit)
task.add_command(task_run)
task.add_command(task_delete)
task.add_command(task_prompt)
task.add_command(task_session_name)


# ──────────────────────────────────────────────────────────────────────────────
# orchestrate
# ──────────────────────────────────────────────────────────────────────────────


@cli.group()
def orchestrate() -> None:
    """Run autonomous orchestration."""


orchestrate.add_command(orchestrate_goal)
orchestrate.add_command(orchestrate_test)
orchestrate.add_command(orchestrate_improve)
orchestrate.add_command(orchestrate_resume)
orchestrate.add_command(orchestrate_fix_from)
orchestrate.add_command(orchestrate_adaptive)


# ──────────────────────────────────────────────────────────────────────────────
# relay
# ──────────────────────────────────────────────────────────────────────────────


@cli.group()
def relay() -> None:
    """Manage cross-device MQTT relay."""


relay.add_command(relay_new)
relay.add_command(relay_connect)
relay.add_command(relay_status)
relay.add_command(relay_on)
relay.add_command(relay_off)


# ──────────────────────────────────────────────────────────────────────────────
# start (external process registration)
# ──────────────────────────────────────────────────────────────────────────────

cli.add_command(start_process)


# ──────────────────────────────────────────────────────────────────────────────
# plugin
# ──────────────────────────────────────────────────────────────────────────────


def _nyi(name: str) -> None:
    """Emit a standard 'not yet implemented' message."""
    click.echo(f"[synapse] '{name}' is not yet implemented.")


@cli.group()
def plugin() -> None:
    """Manage TUI plugins."""


@plugin.command("list")
@click.pass_context
def plugin_list(ctx: click.Context) -> None:
    """List installed TUI plugins."""
    _nyi("plugin list")


@plugin.command("install")
@click.argument("source")
@click.pass_context
def plugin_install(ctx: click.Context, source: str) -> None:
    """Install a TUI plugin from a path or URL."""
    _nyi("plugin install")


@plugin.command("remove")
@click.argument("plugin_name")
@click.pass_context
def plugin_remove(ctx: click.Context, plugin_name: str) -> None:
    """Remove an installed TUI plugin."""
    _nyi("plugin remove")


@plugin.command("check")
@click.pass_context
def plugin_check(ctx: click.Context) -> None:
    """Verify all installed plugins are compatible with this Synapse version."""
    _nyi("plugin check")


# ──────────────────────────────────────────────────────────────────────────────
# hooks
# ──────────────────────────────────────────────────────────────────────────────

from .commands.hooks_cmds import hooks_group

cli.add_command(hooks_group)


# ──────────────────────────────────────────────────────────────────────────────
# config
# ──────────────────────────────────────────────────────────────────────────────

from .commands.config_cmds import config_group

cli.add_command(config_group)


# ──────────────────────────────────────────────────────────────────────────────
# transcript
# ──────────────────────────────────────────────────────────────────────────────

from .commands.transcript_cmds import transcript_group

cli.add_command(transcript_group)


# ──────────────────────────────────────────────────────────────────────────────
# version / update
# ──────────────────────────────────────────────────────────────────────────────

from .commands.version_cmds import name_export, update_cmd, version_cmd

cli.add_command(version_cmd)
cli.add_command(update_cmd)
cli.add_command(name_export)


# ──────────────────────────────────────────────────────────────────────────────
# fork
# ──────────────────────────────────────────────────────────────────────────────

from .commands.fork_cmd import fork_session

cli.add_command(fork_session)


# ──────────────────────────────────────────────────────────────────────────────
# stop / kill
# ──────────────────────────────────────────────────────────────────────────────

from .commands.stop_kill_cmd import kill_session, stop_session

cli.add_command(stop_session)
cli.add_command(kill_session)


# ──────────────────────────────────────────────────────────────────────────────
# listen
# ──────────────────────────────────────────────────────────────────────────────

from .commands.listen_cmd import listen_session

cli.add_command(listen_session)


# ──────────────────────────────────────────────────────────────────────────────
# archive / reset
# ──────────────────────────────────────────────────────────────────────────────

from .commands.archive_reset_cmd import archive_db, reset_all

cli.add_command(archive_db)
cli.add_command(reset_all)


# ──────────────────────────────────────────────────────────────────────────────
# bundle / term
# ──────────────────────────────────────────────────────────────────────────────

from .commands.bundle_term_cmd import bundle_context, term_view

cli.add_command(bundle_context)
cli.add_command(term_view)


# ──────────────────────────────────────────────────────────────────────────────
# extension
# ──────────────────────────────────────────────────────────────────────────────

from .commands.extension_cmds import extension_group

cli.add_command(extension_group)


# ──────────────────────────────────────────────────────────────────────────────
# editor / notify
# ──────────────────────────────────────────────────────────────────────────────

from .commands.editor_notify_cmd import editor_group, notify_cmd

cli.add_command(editor_group)
cli.add_command(notify_cmd)


# ──────────────────────────────────────────────────────────────────────────────
# knowledge
# ──────────────────────────────────────────────────────────────────────────────

from .commands.knowledge_cmds import knowledge_group

cli.add_command(knowledge_group)


# ──────────────────────────────────────────────────────────────────────────────
# daemon
# ──────────────────────────────────────────────────────────────────────────────

from .commands.daemon_cmd import run_daemon

cli.add_command(run_daemon)


# ──────────────────────────────────────────────────────────────────────────────
# resume
# ──────────────────────────────────────────────────────────────────────────────

from .commands.resume_cmd import resume_session

cli.add_command(resume_session)
