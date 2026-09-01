"""Click commands for `synapse message`."""
from __future__ import annotations

import json
import sys

import click

from ...core.config import SynapseConfig
from ...db.database import Database
from ...messaging.messenger import Messenger
from ...session.models import MessageRecord


# ──────────────────────────────────────────────────────────────────────────────
# Shared factory
# ──────────────────────────────────────────────────────────────────────────────


def get_messenger(ctx: click.Context) -> tuple[Messenger, Database]:
    config: SynapseConfig = ctx.obj["config"]
    db = Database(config.db_path)
    return Messenger(db), db


# ──────────────────────────────────────────────────────────────────────────────
# Formatting helper
# ──────────────────────────────────────────────────────────────────────────────


def _fmt_message(msg: MessageRecord) -> str:
    """One-line summary of a message for list views."""
    to_ = msg.to_session_id[:8] if msg.to_session_id else click.style("broadcast", fg="magenta")
    from_ = msg.from_session_id[:8] if msg.from_session_id else click.style("system", fg="bright_black")
    kind_color = {
        "chat": "white",
        "collision": "red",
        "plan": "cyan",
        "result": "green",
        "status": "yellow",
        "questions": "blue",
    }.get(msg.kind or "chat", "white")
    kind = click.style(msg.kind or "chat", fg=kind_color)
    claimed = click.style(" ✓claimed", fg="bright_black") if msg.claimed_at else ""
    thread = f"  thread={msg.thread_id[:8]}" if msg.thread_id else ""
    body_preview = (msg.body or "")[:72].replace("\n", " ")
    return (
        f"  {click.style(str(msg.id), fg='bright_black'):>6}"
        f"  {kind:<10}"
        f"  {from_} → {to_}"
        f"{thread}{claimed}\n"
        f"    {body_preview}"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Commands
# ──────────────────────────────────────────────────────────────────────────────


@click.command("send")
@click.option("--to", "to_session_id", default=None, help="Recipient session ID (omit for broadcast).")
@click.option("--body", required=True, help="Message body text.")
@click.option("--kind", default="chat", show_default=True,
              type=click.Choice(["chat", "questions", "plan", "result", "status", "collision"]),
              help="Message kind.")
@click.option("--from", "from_session_id", default=None, help="Sender session ID.")
@click.option("--thread", "thread_id", default=None, help="Thread ID to attach this message to.")
@click.option("--intent", default="inform", show_default=True,
              type=click.Choice(["request", "inform", "ack"]),
              help="Message intent.")
@click.pass_context
def message_send(
    ctx: click.Context,
    to_session_id: str | None,
    body: str,
    kind: str,
    from_session_id: str | None,
    thread_id: str | None,
    intent: str,
) -> None:
    """Send a message to a session (or broadcast if --to is omitted)."""
    messenger, _ = get_messenger(ctx)
    try:
        msg = messenger.send(
            body=body,
            to_session_id=to_session_id,
            from_session_id=from_session_id,
            kind=kind,
            thread_id=thread_id,
            intent=intent,
        )
    except Exception as exc:
        click.echo(click.style(f"Error: {exc}", fg="red"), err=True)
        sys.exit(1)

    dest = f"session {to_session_id[:8]}" if to_session_id else "broadcast"
    click.echo(
        click.style("✓", fg="green")
        + f" Message {click.style(str(msg.id), fg='bright_black')} sent to {dest}."
    )


@click.command("inbox")
@click.argument("session_id")
@click.option("--limit", default=50, show_default=True, help="Maximum messages to return.")
@click.pass_context
def message_inbox(ctx: click.Context, session_id: str, limit: int) -> None:
    """List unclaimed messages for a session (including broadcasts)."""
    messenger, _ = get_messenger(ctx)
    messages = messenger.inbox(session_id, limit=limit)
    if not messages:
        click.echo("No unclaimed messages.")
        return
    click.echo(f"Inbox for {session_id[:8]} ({len(messages)} message(s)):\n")
    for msg in messages:
        click.echo(_fmt_message(msg))


@click.command("claim")
@click.argument("session_id")
@click.option("--limit", default=10, show_default=True, help="Maximum messages to claim.")
@click.pass_context
def message_claim(ctx: click.Context, session_id: str, limit: int) -> None:
    """Atomically drain (claim) messages addressed to a session."""
    messenger, _ = get_messenger(ctx)
    try:
        messages = messenger.claim(session_id, limit=limit)
    except Exception as exc:
        click.echo(click.style(f"Error: {exc}", fg="red"), err=True)
        sys.exit(1)

    if not messages:
        click.echo("No messages to claim.")
        return
    click.echo(f"Claimed {len(messages)} message(s):\n")
    for msg in messages:
        click.echo(_fmt_message(msg))


@click.command("reply")
@click.argument("message_id", type=int)
@click.argument("text")
@click.option("--from", "from_session_id", default=None, help="Sender session ID.")
@click.pass_context
def message_reply(ctx: click.Context, message_id: int, text: str, from_session_id: str | None) -> None:
    """Reply to a message, preserving its thread."""
    messenger, _ = get_messenger(ctx)
    try:
        msg = messenger.reply(
            original_message_id=message_id,
            body=text,
            from_session_id=from_session_id,
        )
    except ValueError as exc:
        click.echo(click.style(f"Error: {exc}", fg="red"), err=True)
        sys.exit(1)

    click.echo(
        click.style("✓", fg="green")
        + f" Reply {click.style(str(msg.id), fg='bright_black')} sent"
        f" (thread={msg.thread_id or str(message_id)})."
    )


@click.command("subscribe")
@click.argument("session_id")
@click.option("--filter-type", required=True,
              type=click.Choice(["message", "status", "file_edit"]),
              help="Event type to subscribe to.")
@click.option("--filter-spec", default="{}", show_default=True,
              help="JSON object with filter criteria (e.g. '{\"kind\": \"collision\"}').")
@click.pass_context
def message_subscribe(
    ctx: click.Context,
    session_id: str,
    filter_type: str,
    filter_spec: str,
) -> None:
    """Subscribe a session to an event stream."""
    try:
        spec_dict = json.loads(filter_spec)
    except json.JSONDecodeError as exc:
        click.echo(click.style(f"Invalid JSON in --filter-spec: {exc}", fg="red"), err=True)
        sys.exit(1)

    messenger, _ = get_messenger(ctx)
    sub_id = messenger.subscribe(session_id, filter_type=filter_type, filter_spec=spec_dict)
    click.echo(
        click.style("✓", fg="green")
        + f" Subscription {click.style(str(sub_id), fg='bright_black')} created"
        f" for session {session_id[:8]} (type={filter_type})."
    )


@click.command("unsubscribe")
@click.argument("subscription_id", type=int)
@click.pass_context
def message_unsubscribe(ctx: click.Context, subscription_id: int) -> None:
    """Remove a subscription by ID."""
    messenger, _ = get_messenger(ctx)
    ok = messenger.unsubscribe(subscription_id)
    if ok:
        click.echo(click.style("✓", fg="green") + f" Subscription {subscription_id} removed.")
    else:
        click.echo(
            click.style(f"Subscription {subscription_id} not found.", fg="red"),
            err=True,
        )
        sys.exit(1)


@click.command("subscriptions")
@click.argument("session_id")
@click.pass_context
def message_subscriptions(ctx: click.Context, session_id: str) -> None:
    """List subscriptions for a session."""
    messenger, _ = get_messenger(ctx)
    subs = messenger.list_subscriptions(session_id)
    if not subs:
        click.echo(f"No subscriptions for session {session_id[:8]}.")
        return
    click.echo(f"Subscriptions for {session_id[:8]}:\n")
    for sub in subs:
        spec_str = json.dumps(sub.get("filter_spec", {}))
        click.echo(
            f"  {click.style(str(sub['id']), fg='bright_black'):>4}"
            f"  {sub.get('filter_type', ''):<12}"
            f"  {spec_str}"
        )


@click.command("collisions")
@click.option("--window", default=30, show_default=True, help="Time window in seconds.")
@click.pass_context
def message_collisions(ctx: click.Context, window: int) -> None:
    """Detect file-edit collisions between sessions in the last N seconds."""
    messenger, _ = get_messenger(ctx)
    hits = messenger.check_collisions(window_secs=window)
    if not hits:
        click.echo("No collisions detected.")
        return
    click.echo(f"{len(hits)} collision(s) detected:\n")
    for session_a, session_b, file_path in hits:
        click.echo(
            f"  {click.style(session_a[:8], fg='yellow')} ↔ "
            f"{click.style(session_b[:8], fg='yellow')}  {file_path}"
        )
