"""Click commands for `synapse automation`."""
from __future__ import annotations

import sys
import uuid
from typing import Optional

import click

from ...automation.scheduler import AutomationScheduler
from ...backend.tmux import TmuxBackend
from ...core.config import SynapseConfig
from ...db.database import Database
from ...session.manager import SessionManager


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

# Maps human-friendly trigger presets to cron expressions.
_PRESETS: dict[str, tuple[str, str]] = {
    "hourly":   ("cron", "0 * * * *"),
    "daily":    ("cron", "0 9 * * *"),
    "weekly":   ("cron", "0 9 * * 1"),
    "midnight": ("cron", "0 0 * * *"),
    "every5m":  ("cron", "*/5 * * * *"),
    "every15m": ("cron", "*/15 * * * *"),
    "every30m": ("cron", "*/30 * * * *"),
}


def _parse_trigger(trigger: str) -> tuple[str, str]:
    """
    Return (schedule_kind, schedule_spec).

    *trigger* is one of:
    - A preset key from ``_PRESETS`` (e.g. ``"hourly"``).
    - A bare cron expression (5-6 fields, e.g. ``"0 9 * * 1"``).
    - An ISO 8601 datetime string for a one-shot run (e.g. ``"2025-12-31T23:59:00"``).
    """
    if trigger in _PRESETS:
        return _PRESETS[trigger]
    # Heuristic: cron expressions have at least 4 spaces/fields.
    parts = trigger.split()
    if len(parts) in (5, 6) and all(p.replace("*", "").replace("/", "").replace("-", "").replace(",", "").isdigit() or p == "*" for p in parts):
        return ("cron", trigger)
    # Fall through: treat as one-shot ISO datetime.
    return ("once", trigger)


def _get_scheduler(ctx: click.Context) -> tuple[AutomationScheduler, Database]:
    config: SynapseConfig = ctx.obj["config"]
    db = Database(config.db_path)
    tmux = TmuxBackend()
    mgr = SessionManager(db, tmux, config)
    return AutomationScheduler(db, mgr), db


def _fmt_automation(row: dict) -> str:
    """One-line summary of an automation record."""
    enabled = click.style("enabled", fg="green") if row.get("enabled") else click.style("disabled", fg="bright_black")
    kind = click.style(row.get("action_kind") or "?", fg="cyan")
    sched = f"{row.get('schedule_kind','?')}({row.get('schedule_spec','')})"
    last = row.get("last_run_at")
    last_str = f"  last={last}" if last else "  never run"
    return (
        f"  {click.style(str(row['id'])[:8], fg='bright_black')}"
        f"  {click.style(row.get('name') or '(unnamed)', bold=True):<24}"
        f"  [{enabled}]"
        f"  {kind:<8}"
        f"  {sched}"
        f"{last_str}"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Commands
# ──────────────────────────────────────────────────────────────────────────────


@click.command("list")
@click.option("--all", "show_all", is_flag=True, help="Include disabled automations.")
@click.pass_context
def automation_list(ctx: click.Context, show_all: bool) -> None:
    """List all automations with their status and schedule."""
    _, db = _get_scheduler(ctx)
    if show_all:
        rows = db.fetchall(
            "SELECT * FROM automations ORDER BY created_at DESC"
        )
    else:
        rows = db.fetchall(
            "SELECT * FROM automations WHERE enabled=1 ORDER BY created_at DESC"
        )

    if not rows:
        click.echo("No automations found." + (" (use --all to see disabled)" if not show_all else ""))
        return

    click.echo(f"{len(rows)} automation(s):\n")
    for row in rows:
        click.echo(_fmt_automation(dict(row)))


@click.command("create")
@click.option("--name", required=True, help="Automation name.")
@click.option(
    "--trigger",
    required=True,
    help=(
        "Cron expression, preset (hourly/daily/weekly/midnight/every5m/every15m/every30m), "
        "or ISO 8601 datetime for a one-shot run."
    ),
)
@click.option("--prompt", default=None, help="Prompt text to send or use when spawning.")
@click.option("--session", "target_session", default=None, help="Target session ID (for --action send).")
@click.option("--repo-path", default=None, help="Repository path (for --action spawn).")
@click.option("--agent", default=None, help="Agent name (for --action spawn).")
@click.option("--branch", default=None, help="Worktree branch (for --action spawn).")
@click.option("--command", "exec_command", default=None, help="Shell command (for --action exec).")
@click.option(
    "--action",
    "action_kind",
    default=None,
    type=click.Choice(["send", "spawn", "exec"]),
    help="Action kind. Auto-detected if omitted.",
)
@click.option("--tz", "timezone", default="UTC", show_default=True, help="Timezone for schedule.")
@click.pass_context
def automation_create(
    ctx: click.Context,
    name: str,
    trigger: str,
    prompt: Optional[str],
    target_session: Optional[str],
    repo_path: Optional[str],
    agent: Optional[str],
    branch: Optional[str],
    exec_command: Optional[str],
    action_kind: Optional[str],
    timezone: str,
) -> None:
    """Create a new automation rule."""
    scheduler, db = _get_scheduler(ctx)

    # Auto-detect action kind when not specified.
    if action_kind is None:
        if exec_command:
            action_kind = "exec"
        elif repo_path:
            action_kind = "spawn"
        elif target_session:
            action_kind = "send"
        else:
            click.echo(
                click.style(
                    "Error: Cannot determine action kind. Provide --action, --session, --repo-path, or --command.",
                    fg="red",
                ),
                err=True,
            )
            sys.exit(1)

    schedule_kind, schedule_spec = _parse_trigger(trigger)
    next_run_at = scheduler.compute_initial_next_run(schedule_kind, schedule_spec, timezone)
    now_ms = db.now_ms()
    auto_id = str(uuid.uuid4())

    db.execute(
        """
        INSERT INTO automations (
            id, name, enabled,
            schedule_kind, schedule_spec, timezone,
            action_kind, action_target_session, action_repo_path,
            action_worktree_branch, action_agent, action_command,
            prompt, next_run_at, created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            auto_id, name, 1,
            schedule_kind, schedule_spec, timezone,
            action_kind, target_session, repo_path,
            branch, agent, exec_command,
            prompt, next_run_at, now_ms, now_ms,
        ),
    )
    click.echo(
        click.style("✓", fg="green")
        + f" Automation {click.style(name, bold=True)}"
        + f" created (id={click.style(auto_id[:8], fg='bright_black')}"
        + f", {schedule_kind}={schedule_spec}"
        + f", action={action_kind})."
    )


@click.command("edit")
@click.argument("automation_id")
@click.option("--name", default=None, help="New name.")
@click.option("--trigger", default=None, help="New trigger (cron expression or preset).")
@click.option("--prompt", default=None, help="New prompt text.")
@click.option("--session", "target_session", default=None, help="New target session ID.")
@click.option("--enabled/--disabled", default=None, help="Enable or disable the automation.")
@click.option("--tz", "timezone", default=None, help="New timezone.")
@click.pass_context
def automation_edit(
    ctx: click.Context,
    automation_id: str,
    name: Optional[str],
    trigger: Optional[str],
    prompt: Optional[str],
    target_session: Optional[str],
    enabled: Optional[bool],
    timezone: Optional[str],
) -> None:
    """Edit an existing automation."""
    scheduler, db = _get_scheduler(ctx)

    row = db.fetchone(
        "SELECT * FROM automations WHERE id=? OR id LIKE ?",
        (automation_id, f"{automation_id}%"),
    )
    if row is None:
        click.echo(click.style(f"Automation '{automation_id}' not found.", fg="red"), err=True)
        sys.exit(1)

    auto = dict(row)
    now_ms = db.now_ms()
    updates: list[str] = ["updated_at=?"]
    values: list = [now_ms]

    if name is not None:
        updates.append("name=?")
        values.append(name)

    if trigger is not None:
        schedule_kind, schedule_spec = _parse_trigger(trigger)
        tz = timezone or auto.get("timezone") or "UTC"
        next_run_at = scheduler.compute_initial_next_run(schedule_kind, schedule_spec, tz)
        updates += ["schedule_kind=?", "schedule_spec=?", "next_run_at=?"]
        values += [schedule_kind, schedule_spec, next_run_at]

    if timezone is not None:
        updates.append("timezone=?")
        values.append(timezone)

    if prompt is not None:
        updates.append("prompt=?")
        values.append(prompt)

    if target_session is not None:
        updates.append("action_target_session=?")
        values.append(target_session)

    if enabled is not None:
        updates.append("enabled=?")
        values.append(1 if enabled else 0)

    values.append(auto["id"])
    db.execute(
        f"UPDATE automations SET {', '.join(updates)} WHERE id=?",
        values,
    )
    click.echo(
        click.style("✓", fg="green")
        + f" Automation {click.style(auto['id'][:8], fg='bright_black')} updated."
    )


@click.command("delete")
@click.argument("automation_id")
@click.option("--hard", is_flag=True, help="Permanently remove instead of soft-delete.")
@click.pass_context
def automation_delete(ctx: click.Context, automation_id: str, hard: bool) -> None:
    """Delete (soft-delete by default) an automation."""
    _, db = _get_scheduler(ctx)

    row = db.fetchone(
        "SELECT * FROM automations WHERE id=? OR id LIKE ?",
        (automation_id, f"{automation_id}%"),
    )
    if row is None:
        click.echo(click.style(f"Automation '{automation_id}' not found.", fg="red"), err=True)
        sys.exit(1)

    auto = dict(row)
    if hard:
        db.execute("DELETE FROM automations WHERE id=?", (auto["id"],))
        verb = "deleted"
    else:
        # Soft-delete: disable and record timestamp in name as a marker
        db.execute(
            "UPDATE automations SET enabled=0, name=('[deleted] ' || name) WHERE id=?",
            (auto["id"],),
        )
        verb = "disabled (soft-deleted)"

    click.echo(
        click.style("✓", fg="green")
        + f" Automation {click.style(auto['id'][:8], fg='bright_black')} {verb}."
    )


@click.command("trigger")
@click.argument("automation_id")
@click.pass_context
def automation_trigger(ctx: click.Context, automation_id: str) -> None:
    """Manually fire an automation immediately, regardless of its schedule."""
    scheduler, db = _get_scheduler(ctx)

    row = db.fetchone(
        "SELECT * FROM automations WHERE id=? OR id LIKE ?",
        (automation_id, f"{automation_id}%"),
    )
    if row is None:
        click.echo(click.style(f"Automation '{automation_id}' not found.", fg="red"), err=True)
        sys.exit(1)

    auto = dict(row)
    now_ms = db.now_ms()

    click.echo(f"Triggering automation {click.style(auto['name'] or auto['id'][:8], bold=True)} …")
    scheduler._fire(auto, now_ms)
    click.echo(click.style("✓", fg="green") + " Automation fired.")


@click.command("history")
@click.argument("automation_id", required=False)
@click.option("--limit", default=20, show_default=True, help="Number of runs to show.")
@click.pass_context
def automation_history(ctx: click.Context, automation_id: Optional[str], limit: int) -> None:
    """Show run history for automations.

    If AUTOMATION_ID is provided, shows history for that automation only.
    Without an argument, shows recent history across all automations.
    """
    _, db = _get_scheduler(ctx)

    if automation_id:
        # Resolve automation ID
        row = db.fetchone(
            "SELECT id, name FROM automations WHERE id=? OR id LIKE ?",
            (automation_id, f"{automation_id}%"),
        )
        if row is None:
            click.echo(click.style(f"Automation '{automation_id}' not found.", fg="red"), err=True)
            sys.exit(1)
        auto_id = row["id"]
        click.echo(f"\n  History for {click.style(row['name'] or auto_id[:8], bold=True)}:\n")
        runs = db.fetchall(
            "SELECT * FROM automation_runs WHERE automation_id=? ORDER BY fired_at DESC LIMIT ?",
            (auto_id, limit),
        )
    else:
        click.echo("\n  Recent automation runs:\n")
        runs = db.fetchall(
            "SELECT * FROM automation_runs ORDER BY fired_at DESC LIMIT ?",
            (limit,),
        )

    if not runs:
        click.echo("  No runs recorded.")
        return

    for run in runs:
        r = dict(run)
        fired = r.get("fired_at") or 0
        from datetime import datetime, timezone
        ts = datetime.fromtimestamp(fired / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC") if fired else "?"
        success = click.style("✓", fg="green") if r.get("success") else click.style("✗", fg="red")
        name = r.get("automation_name") or r.get("automation_id", "?")[:8]
        kind = r.get("action_kind") or "?"
        result = (r.get("result") or "")[:50]
        click.echo(f"    {success} {ts}  {click.style(name, fg='cyan'):<20} [{kind}] {result}")

