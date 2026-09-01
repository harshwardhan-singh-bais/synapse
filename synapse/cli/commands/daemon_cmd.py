"""Click command for `synapse daemon` — run the relay worker as a background daemon."""
from __future__ import annotations

import sys
import time

import click

from ...core.config import SynapseConfig
from ...db.database import Database
from ...relay.mqtt_relay import MQTTRelay, RelayConfig
from ...session.manager import SessionManager
from ...backend.tmux import TmuxBackend


@click.command("daemon")
@click.option("--foreground", "-f", is_flag=True, help="Run in foreground (don't fork).")
@click.option("--pid-file", default=None, help="PID file path.")
@click.pass_context
def run_daemon(ctx: click.Context, foreground: bool, pid_file: str | None) -> None:
    """Run the Synapse relay daemon in the background.

    Connects to the MQTT relay and handles cross-device message dispatch.
    Use --foreground to run in the current terminal (useful for debugging).
    """
    config: SynapseConfig = ctx.obj["config"]
    db = Database(config.db_path)

    if not config.relay_enabled:
        click.echo(click.style("Relay is not enabled. Use `synapse relay new` to set up.", fg="yellow"))
        return

    relay_config = RelayConfig(db)
    if not relay_config.url:
        click.echo(click.style("No relay URL configured. Use `synapse relay new` to set up.", fg="yellow"))
        return

    # Write PID file
    if pid_file:
        import os
        from pathlib import Path
        pid_path = Path(pid_file)
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        pid_path.write_text(str(os.getpid()), encoding="utf-8")

    click.echo(
        click.style("⚡", fg="cyan")
        + f" Synapse relay daemon starting..."
        f"  url={relay_config.url}"
        f"  id={relay_config.relay_id[:8]}"
    )

    # Create the relay
    def on_message(payload: dict) -> None:
        """Handle incoming relay messages."""
        msg_type = payload.get("type", "msg")
        if msg_type == "msg":
            # Route to the messaging system
            from ...messaging.messenger import Messenger
            messenger = Messenger(db)
            body = payload.get("body", "")
            from_session = payload.get("from_session_id")
            to_session = payload.get("to_session_id")
            if body:
                messenger.send(
                    body=body,
                    to_session_id=to_session,
                    from_session_id=from_session,
                    kind=payload.get("kind", "chat"),
                )
        elif msg_type == "rpc":
            # Handle RPC commands
            method = payload.get("method", "")
            if method == "ping":
                relay.publish_rpc(
                    payload.get("from_relay_id", ""),
                    "pong",
                    {"relay_id": relay_config.relay_id},
                )

    relay = MQTTRelay(relay_config, db, on_message=on_message)
    relay.start()

    click.echo(click.style("  ✓ Relay daemon running.", fg="green"))
    click.echo("  Press Ctrl+C to stop.")

    try:
        while True:
            time.sleep(60)
            # Publish periodic state update
            relay.publish_state({
                "status": "online",
                "capabilities": ["msg", "ctrl"],
                "uptime": int(time.time()),
            })
    except KeyboardInterrupt:
        click.echo("\n  Stopping relay daemon...")
        relay.publish_gone()
        relay.stop()
        click.echo(click.style("  ✓ Relay daemon stopped.", fg="green"))
    finally:
        if pid_file:
            try:
                from pathlib import Path
                Path(pid_file).unlink(missing_ok=True)
            except Exception:
                pass
