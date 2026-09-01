"""Click commands for `synapse relay`."""
from __future__ import annotations

import sys

import click

from ...core.config import SynapseConfig
from ...db.database import Database
from ...relay.mqtt_relay import MQTTRelay, RelayConfig


# ──────────────────────────────────────────────────────────────────────────────
# Shared factory
# ──────────────────────────────────────────────────────────────────────────────


def _get_relay_config(ctx: click.Context) -> tuple[RelayConfig, Database]:
    config: SynapseConfig = ctx.obj["config"]
    db = Database(config.db_path)
    return RelayConfig(db), db


# ──────────────────────────────────────────────────────────────────────────────
# Commands
# ──────────────────────────────────────────────────────────────────────────────


@click.command("new")
@click.option(
    "--url",
    required=True,
    help="MQTT broker URL, e.g. mqtt://broker.emqx.io:1883 or mqtts://broker.emqx.io:8883",
)
@click.pass_context
def relay_new(ctx: click.Context, url: str) -> None:
    """Provision a new relay channel and print the join token for other devices."""
    relay_cfg, _ = _get_relay_config(ctx)
    token = relay_cfg.generate_new(url)

    click.echo("\n" + click.style("⚡ New relay channel provisioned!", fg="green", bold=True))
    click.echo(f"\n  Relay ID : {click.style(relay_cfg.relay_id, fg='cyan')}")
    click.echo(f"  URL      : {url}")
    click.echo(f"\n  Join token (share this with other devices):\n")
    click.echo("    " + click.style(token, fg="yellow", bold=True))
    click.echo(
        "\n  On another machine run:\n"
        f"    synapse relay connect {token!r} --url {url!r}\n"
    )


@click.command("connect")
@click.argument("token")
@click.option(
    "--url",
    required=True,
    help="MQTT broker URL (must match the one used when the relay was provisioned).",
)
@click.pass_context
def relay_connect(ctx: click.Context, token: str, url: str) -> None:
    """Join an existing relay channel using a join token."""
    relay_cfg, _ = _get_relay_config(ctx)
    try:
        relay_cfg.connect_from_token(token, url)
    except ValueError as exc:
        click.echo(click.style(f"Error: {exc}", fg="red"), err=True)
        sys.exit(1)

    click.echo(
        click.style("✓", fg="green")
        + f" Joined relay {click.style(relay_cfg.relay_id, fg='cyan')} via {url}."
    )
    click.echo("  Relay is now " + click.style("enabled", fg="green") + ". Run `synapse relay status` to verify.")


@click.command("status")
@click.pass_context
def relay_status(ctx: click.Context) -> None:
    """Show relay configuration and live connection health."""
    relay_cfg, _ = _get_relay_config(ctx)

    relay_id = relay_cfg.get("relay_id") or click.style("(not set)", fg="bright_black")
    url = relay_cfg.url or click.style("(not set)", fg="bright_black")
    enabled = relay_cfg.enabled

    enabled_str = (
        click.style("enabled", fg="green") if enabled else click.style("disabled", fg="bright_black")
    )

    click.echo(f"\n  Relay status : {enabled_str}")
    click.echo(f"  Relay ID     : {relay_id}")
    click.echo(f"  Broker URL   : {url}")

    if enabled and relay_cfg.url:
        # Perform a quick connectivity probe.
        click.echo(f"\n  Probing connection …", nl=False)
        relay = MQTTRelay(relay_cfg, _get_relay_config(ctx)[1])
        relay.start()

        import time
        for _ in range(30):  # wait up to 3 s
            if relay.is_connected():
                break
            time.sleep(0.1)

        if relay.is_connected():
            click.echo("\r  " + click.style("● Connected", fg="green") + "          ")
        else:
            err = relay.last_error or "timed out"
            click.echo("\r  " + click.style(f"○ Disconnected — {err}", fg="red") + "    ")
        relay.stop()
    else:
        click.echo()
        click.echo("  " + click.style("Relay is disabled. Run `synapse relay on` to enable.", fg="bright_black"))
    click.echo()


@click.command("on")
@click.pass_context
def relay_on(ctx: click.Context) -> None:
    """Enable the relay (requires a prior `synapse relay new` or `connect`)."""
    relay_cfg, _ = _get_relay_config(ctx)

    if not relay_cfg.url:
        click.echo(
            click.style(
                "Error: No relay URL configured. Run `synapse relay new --url ...` first.",
                fg="red",
            ),
            err=True,
        )
        sys.exit(1)

    relay_cfg.enable()
    click.echo(click.style("✓", fg="green") + " Relay enabled.")


@click.command("off")
@click.pass_context
def relay_off(ctx: click.Context) -> None:
    """Disable the relay (does not remove configuration)."""
    relay_cfg, _ = _get_relay_config(ctx)
    relay_cfg.disable()
    click.echo(click.style("✓", fg="green") + " Relay disabled.")
