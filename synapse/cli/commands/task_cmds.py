"""Click commands for `synapse task`."""
from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from typing import Optional

import click

from ...backend.tmux import TmuxBackend
from ...core.config import SynapseConfig
from ...db.database import Database
from ...session.manager import SessionManager
from ...session.models import TaskRecord


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

_VALID_STATUSES = ("todo", "in_progress", "done")

_STATUS_COLORS: dict[str, str] = {
    "todo":        "white",
    "in_progress": "yellow",
    "done":        "green",
}


def _get_db(ctx: click.Context) -> Database:
    config: SynapseConfig = ctx.obj["config"]
    return Database(config.db_path)


def _get_managers(ctx: click.Context) -> tuple[SessionManager, Database]:
    config: SynapseConfig = ctx.obj["config"]
    db = Database(config.db_path)
    return SessionManager(db, TmuxBackend(), config), db


def _row_to_task(row: object) -> TaskRecord:
    return TaskRecord.model_validate(dict(row))  # type: ignore[call-overload, arg-type]


def _task_to_agent_prompt(task: TaskRecord) -> str:
    """Generate an agent prompt from a task's title and description."""
    parts: list[str] = []
    if task.title:
        parts.append(f"Task: {task.title}")
    if task.description:
        parts.append(f"\nDescription:\n{task.description}")
    if task.action_kind:
        parts.append(f"\nAction type: {task.action_kind}")
    if task.action_command:
        parts.append(f"Command: {task.action_command}")
    if task.action_repo_path:
        parts.append(f"Repository: {task.action_repo_path}")
    parts.append("\nPlease complete this task and report back when done.")
    return "\n".join(parts)


def _task_to_session_name(task: TaskRecord) -> str:
    """Generate a unique session name from a task's title.

    Produces a short, readable, deterministic name like 'task-42-refactor-auth' or
    'task-7-upgrade-deps'.  Falls back to 'task-<id>' for empty titles.
    """
    base = task.title or ""
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", base.lower()).strip("-")[:40]
    if not slug:
        slug = "work"
    # Append a short hash for uniqueness across same-titled tasks
    hash_seed = f"{task.id}-{base}"
    short_hash = hashlib.md5(hash_seed.encode()).hexdigest()[:4]
    return f"task-{task.id}-{slug}-{short_hash}"


def _fmt_task_oneline(task: TaskRecord) -> str:
    color = _STATUS_COLORS.get(task.status, "white")
    status_str = click.style(f"[{task.status}]", fg=color)
    title = click.style(task.title or "(no title)", bold=True)
    desc = f"  {(task.description or '')[:60]}" if task.description else ""
    action = f"  action={task.action_kind}" if task.action_kind else ""
    return f"  {click.style(str(task.id), fg='bright_black'):>6}  {status_str:<18}  {title}{action}{desc}"


# ──────────────────────────────────────────────────────────────────────────────
# Commands
# ──────────────────────────────────────────────────────────────────────────────


@click.command("list")
@click.option(
    "--status",
    default=None,
    type=click.Choice(_VALID_STATUSES),
    help="Filter by status.",
)
@click.option("--all", "show_all", is_flag=True, help="Include completed and deleted tasks.")
@click.pass_context
def task_list(ctx: click.Context, status: Optional[str], show_all: bool) -> None:
    """List tasks, optionally filtered by status."""
    db = _get_db(ctx)

    if show_all:
        sql = "SELECT * FROM tasks ORDER BY created_at DESC"
        params: tuple = ()
    elif status:
        sql = "SELECT * FROM tasks WHERE status=? AND deleted_at IS NULL ORDER BY created_at DESC"
        params = (status,)
    else:
        sql = "SELECT * FROM tasks WHERE deleted_at IS NULL ORDER BY created_at DESC"
        params = ()

    rows = db.fetchall(sql, params)
    if not rows:
        click.echo("No tasks found.")
        return

    click.echo(f"{len(rows)} task(s):\n")
    for row in rows:
        click.echo(_fmt_task_oneline(_row_to_task(row)))


@click.command("show")
@click.argument("task_id", type=int)
@click.pass_context
def task_show(ctx: click.Context, task_id: int) -> None:
    """Show full details for a single task."""
    db = _get_db(ctx)
    row = db.fetchone("SELECT * FROM tasks WHERE id=?", (task_id,))
    if row is None:
        click.echo(click.style(f"Task {task_id} not found.", fg="red"), err=True)
        sys.exit(1)

    task = _row_to_task(row)
    color = _STATUS_COLORS.get(task.status, "white")

    click.echo(f"\n  {click.style('Task', bold=True)} {click.style(str(task.id), fg='bright_black')}\n")
    click.echo(f"  title:        {task.title or ''}")
    click.echo(f"  status:       {click.style(task.status, fg=color)}")
    click.echo(f"  description:  {task.description or ''}")
    click.echo(f"  source:       {task.source}")
    if task.action_kind:
        click.echo(f"\n  action_kind:          {task.action_kind}")
    if task.action_target_session:
        click.echo(f"  action_target_session: {task.action_target_session}")
    if task.action_repo_path:
        click.echo(f"  action_repo_path:      {task.action_repo_path}")
    if task.action_worktree_branch:
        click.echo(f"  action_worktree_branch:{task.action_worktree_branch}")
    if task.action_agent:
        click.echo(f"  action_agent:          {task.action_agent}")
    if task.action_command:
        click.echo(f"  action_command:        {task.action_command}")
    if task.external_url:
        click.echo(f"\n  external_url: {task.external_url}")
    click.echo()


@click.command("create")
@click.option("--title", required=True, help="Short title for the task.")
@click.option("--description", default=None, help="Longer description.")
@click.option(
    "--action",
    "action_kind",
    default=None,
    type=click.Choice(["send", "spawn", "exec"]),
    help="Action to take when the task is run.",
)
@click.option("--send-to", "target_session", default=None, help="Session to send a prompt to (action=send).")
@click.option("--repo-path", default=None, help="Repo path for spawning a session (action=spawn).")
@click.option("--agent", default=None, help="Agent to use when spawning (action=spawn).")
@click.option("--branch", default=None, help="Worktree branch (action=spawn).")
@click.option("--command", "exec_command", default=None, help="Shell command (action=exec).")
@click.option("--prompt", default=None, help="Prompt text to send.")
@click.pass_context
def task_create(
    ctx: click.Context,
    title: str,
    description: Optional[str],
    action_kind: Optional[str],
    target_session: Optional[str],
    repo_path: Optional[str],
    agent: Optional[str],
    branch: Optional[str],
    exec_command: Optional[str],
    prompt: Optional[str],
) -> None:
    """Create a new task."""
    db = _get_db(ctx)
    now_ms = db.now_ms()

    # Auto-detect action kind.
    if action_kind is None:
        if exec_command:
            action_kind = "exec"
        elif repo_path:
            action_kind = "spawn"
        elif target_session:
            action_kind = "send"

    cur = db.execute(
        """
        INSERT INTO tasks (
            title, description, status,
            action_kind, action_target_session, action_repo_path,
            action_worktree_branch, action_agent, action_command,
            source, created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            title, description or prompt, "todo",
            action_kind, target_session, repo_path,
            branch, agent, exec_command,
            "local", now_ms, now_ms,
        ),
    )
    task_id = cur.lastrowid
    click.echo(
        click.style("✓", fg="green")
        + f" Task {click.style(str(task_id), fg='bright_black')} created:"
        + f" {click.style(title, bold=True)}"
        + (f" [action={action_kind}]" if action_kind else "")
    )

    # Optionally queue a message to an existing session.
    if target_session and prompt and action_kind == "send":
        from ...messaging.messenger import Messenger
        messenger = Messenger(db)
        messenger.send(
            body=f"[Task #{task_id}] {prompt}",
            to_session_id=target_session,
            kind="chat",
            intent="request",
        )
        click.echo(
            click.style("  →", fg="blue")
            + f" Prompt queued to session {click.style(target_session[:8], fg='bright_black')}."
        )


@click.command("edit")
@click.argument("task_id", type=int)
@click.option("--title", default=None, help="New title.")
@click.option(
    "--status",
    default=None,
    type=click.Choice(_VALID_STATUSES),
    help="New status.",
)
@click.option("--description", default=None, help="New description.")
@click.option("--action", "action_kind", default=None,
              type=click.Choice(["send", "spawn", "exec"]), help="New action kind.")
@click.option("--session", "target_session", default=None, help="New target session.")
@click.pass_context
def task_edit(
    ctx: click.Context,
    task_id: int,
    title: Optional[str],
    status: Optional[str],
    description: Optional[str],
    action_kind: Optional[str],
    target_session: Optional[str],
) -> None:
    """Edit a task's title, status, or description."""
    db = _get_db(ctx)
    row = db.fetchone("SELECT * FROM tasks WHERE id=? AND deleted_at IS NULL", (task_id,))
    if row is None:
        click.echo(click.style(f"Task {task_id} not found.", fg="red"), err=True)
        sys.exit(1)

    now_ms = db.now_ms()
    updates: list[str] = ["updated_at=?"]
    values: list = [now_ms]

    if title is not None:
        updates.append("title=?")
        values.append(title)
    if status is not None:
        updates.append("status=?")
        values.append(status)
    if description is not None:
        updates.append("description=?")
        values.append(description)
    if action_kind is not None:
        updates.append("action_kind=?")
        values.append(action_kind)
    if target_session is not None:
        updates.append("action_target_session=?")
        values.append(target_session)

    values.append(task_id)
    db.execute(f"UPDATE tasks SET {', '.join(updates)} WHERE id=?", values)
    click.echo(
        click.style("✓", fg="green")
        + f" Task {click.style(str(task_id), fg='bright_black')} updated."
    )


@click.command("run")
@click.argument("task_id", type=int)
@click.pass_context
def task_run(ctx: click.Context, task_id: int) -> None:
    """Execute a task's action immediately and mark it in_progress → done."""
    mgr, db = _get_managers(ctx)
    row = db.fetchone("SELECT * FROM tasks WHERE id=? AND deleted_at IS NULL", (task_id,))
    if row is None:
        click.echo(click.style(f"Task {task_id} not found.", fg="red"), err=True)
        sys.exit(1)

    task = _row_to_task(row)
    now_ms = db.now_ms()

    db.execute("UPDATE tasks SET status='in_progress', updated_at=? WHERE id=?", (now_ms, task_id))

    click.echo(f"Running task {click.style(str(task_id), fg='bright_black')}: {task.title} …")

    success = True
    try:
        kind = task.action_kind or ""
        if kind == "send":
            target = task.action_target_session
            body = task.description or task.title or ""
            if target and body:
                mgr.send_text(target, body)
            else:
                click.echo(click.style("  ⚠ No target session or body set.", fg="yellow"))

        elif kind == "spawn":
            repo = task.action_repo_path
            agent = task.action_agent or "claude"
            branch = task.action_worktree_branch
            if repo:
                # Use task-derived session name and agent prompt
                session_name = _task_to_session_name(task)
                agent_prompt = _task_to_agent_prompt(task)
                session = mgr.create_session(
                    name=session_name,
                    repo_path=repo,
                    agent=agent,
                    worktree_branch=branch,
                    tag="task",
                )
                if agent_prompt:
                    mgr.send_text(session.id, agent_prompt)
                click.echo(
                    click.style("  →", fg="blue")
                    + f" Session {click.style(session_name, fg='bright_black')} spawned."
                )
            else:
                click.echo(click.style("  ⚠ No repo path set.", fg="yellow"))

        elif kind == "exec":
            cmd = task.action_command
            if cmd:
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True)  # noqa: S602
                if result.stdout:
                    click.echo(result.stdout)
                if result.returncode != 0:
                    click.echo(click.style(f"  ⚠ Command exited {result.returncode}", fg="yellow"))
                    if result.stderr:
                        click.echo(click.style(result.stderr, fg="red"), err=True)
            else:
                click.echo(click.style("  ⚠ No command set.", fg="yellow"))

        else:
            click.echo(click.style(f"  ⚠ Unknown action kind '{kind}'. Marking done anyway.", fg="yellow"))

    except Exception as exc:
        success = False
        click.echo(click.style(f"  Error: {exc}", fg="red"), err=True)

    final_status = "done" if success else "todo"
    db.execute(
        "UPDATE tasks SET status=?, updated_at=? WHERE id=?",
        (final_status, db.now_ms(), task_id),
    )
    if success:
        click.echo(click.style("✓", fg="green") + f" Task {task_id} completed.")
    else:
        click.echo(click.style("✗", fg="red") + f" Task {task_id} failed; reset to 'todo'.")


@click.command("delete")
@click.argument("task_id", type=int)
@click.option("--hard", is_flag=True, help="Permanently remove instead of soft-delete.")
@click.pass_context
def task_delete(ctx: click.Context, task_id: int, hard: bool) -> None:
    """Soft-delete (or hard-delete with --hard) a task."""
    db = _get_db(ctx)
    row = db.fetchone("SELECT id FROM tasks WHERE id=? AND deleted_at IS NULL", (task_id,))
    if row is None:
        click.echo(click.style(f"Task {task_id} not found.", fg="red"), err=True)
        sys.exit(1)

    if hard:
        db.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        verb = "deleted"
    else:
        db.execute(
            "UPDATE tasks SET deleted_at=?, updated_at=? WHERE id=?",
            (db.now_ms(), db.now_ms(), task_id),
        )
        verb = "soft-deleted"

    click.echo(
        click.style("✓", fg="green")
        + f" Task {click.style(str(task_id), fg='bright_black')} {verb}."
    )


@click.command("prompt")
@click.argument("task_id", type=int)
@click.pass_context
def task_prompt(ctx: click.Context, task_id: int) -> None:
    """Show the agent prompt that would be generated for a task."""
    db = _get_db(ctx)
    row = db.fetchone("SELECT * FROM tasks WHERE id=? AND deleted_at IS NULL", (task_id,))
    if row is None:
        click.echo(click.style(f"Task {task_id} not found.", fg="red"), err=True)
        sys.exit(1)
    task = _row_to_task(row)
    click.echo(_task_to_agent_prompt(task))


@click.command("session-name")
@click.argument("task_id", type=int)
@click.pass_context
def task_session_name(ctx: click.Context, task_id: int) -> None:
    """Show the session name that would be generated for a task."""
    db = _get_db(ctx)
    row = db.fetchone("SELECT * FROM tasks WHERE id=? AND deleted_at IS NULL", (task_id,))
    if row is None:
        click.echo(click.style(f"Task {task_id} not found.", fg="red"), err=True)
        sys.exit(1)
    task = _row_to_task(row)
    click.echo(_task_to_session_name(task))