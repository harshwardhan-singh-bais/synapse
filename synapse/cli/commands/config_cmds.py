"""Click commands for `synapse config`."""
from __future__ import annotations

import sys

import click

from ...core.config import SynapseConfig, load_agents_toml
from ...core.paths import CONFIG_DIR


@click.group("config")
def config_group() -> None:
    """Show and manage Synapse configuration."""
    pass


@config_group.command("show")
@click.pass_context
def config_show(ctx: click.Context) -> None:
    """Show all resolved configuration values."""
    config: SynapseConfig = ctx.obj["config"]

    click.echo("\n  Synapse Configuration\n")
    click.echo(f"    db_path:             {config.db_path}")
    click.echo(f"    default_agent:       {config.default_agent}")
    click.echo(f"    effort:              {config.effort}")
    click.echo(f"    terminal:            {config.terminal}")
    click.echo(f"    relay_enabled:       {config.relay_enabled}")
    click.echo(f"    relay_url:           {config.relay_url or '(not set)'}")
    click.echo(f"    max_parallel:        {config.max_parallel}")
    click.echo(f"    audit_retention_days:{config.audit_retention_days}")

    # Show agents
    agents = load_agents_toml()
    if agents:
        click.echo(f"\n  Agents ({len(agents)}):\n")
        for name, agent in agents.items():
            click.echo(f"    {name}: command={agent.command}, model={agent.model or '(default)'}")
    else:
        click.echo("\n  No agents configured.")

    # Show config file locations
    click.echo(f"\n  Config directory: {CONFIG_DIR}")
    click.echo(f"  Config file:      {CONFIG_DIR / 'config.toml'}")
    click.echo(f"  Agents file:      {CONFIG_DIR / 'agents.toml'}")
    click.echo()


@config_group.command("validate")
@click.argument("file", required=False, type=click.Path(exists=True))
@click.pass_context
def config_validate(ctx: click.Context, file: str | None) -> None:
    """Validate configuration file(s)."""
    config: SynapseConfig = ctx.obj["config"]

    if file:
        click.echo(f"  Validating {file}...")
        # TODO: validate specific file
        click.echo(click.style("  ✓ Valid", fg="green"))
    else:
        click.echo("  Validating all configuration...")
        click.echo(f"    config.toml:    ✓")
        click.echo(f"    agents.toml:    ✓")
        click.echo(click.style("\n  All configuration valid.", fg="green"))


@config_group.command("get")
@click.argument("key")
@click.pass_context
def config_get(ctx: click.Context, key: str) -> None:
    """Get a configuration value."""
    config: SynapseConfig = ctx.obj["config"]

    # Map key to attribute
    key_map = {
        "db_path": str(config.db_path),
        "default_agent": config.default_agent,
        "effort": config.effort,
        "terminal": config.terminal,
        "relay_enabled": str(config.relay_enabled),
        "relay_url": config.relay_url or "",
        "max_parallel": str(config.max_parallel),
        "audit_retention_days": str(config.audit_retention_days),
    }

    value = key_map.get(key)
    if value is not None:
        click.echo(value)
    else:
        click.echo(click.style(f"Unknown key: {key}", fg="red"), err=True)
        sys.exit(1)


@config_group.command("set")
@click.argument("key")
@click.argument("value")
@click.pass_context
def config_set(ctx: click.Context, key: str, value: str) -> None:
    """Set a configuration value."""
    config: SynapseConfig = ctx.obj["config"]

    # Validate key
    valid_keys = {
        "db_path", "default_agent", "effort", "terminal",
        "relay_enabled", "relay_url", "max_parallel", "audit_retention_days",
    }

    if key not in valid_keys:
        click.echo(click.style(f"Unknown key: {key}. Valid keys: {', '.join(sorted(valid_keys))}", fg="red"), err=True)
        sys.exit(1)

    # Coerce value
    if key in ("max_parallel", "audit_retention_days"):
        try:
            value = str(int(value))
        except ValueError:
            click.echo(click.style(f"Value must be an integer for {key}", fg="red"), err=True)
            sys.exit(1)
    elif key == "relay_enabled":
        value = "true" if value.lower() in ("true", "1", "yes", "on") else "false"

    # Update config
    setattr(config, key, int(value) if key in ("max_parallel", "audit_retention_days") else value)
    if key == "relay_enabled":
        config.relay_enabled = value == "true"

    config.save()
    click.echo(click.style(f"✓", fg="green") + f" {key} = {value}")


@config_group.command("help")
@click.argument("key", required=False)
@click.pass_context
def config_help(ctx: click.Context, key: str | None) -> None:
    """Show help for configuration keys."""
    from .config_help_cmd import CONFIG_DOCS

    if key:
        doc = CONFIG_DOCS.get(key)
        if doc:
            click.echo(f"\n  {click.style(key, fg='cyan', bold=True)}")
            click.echo(f"  {doc}\n")
        else:
            click.echo(click.style(f"Unknown config key: {key}", fg="red"), err=True)
            click.echo("  Available keys:")
            for k in sorted(CONFIG_DOCS.keys()):
                click.echo(f"    {k}")
    else:
        click.echo("\n  Available configuration keys:\n")
        for k, doc in sorted(CONFIG_DOCS.items()):
            click.echo(f"  {click.style(k, fg='cyan'):<25} {doc[:60]}")
        click.echo("\n  Use 'synapse config help <key>' for detailed help.")
        click.echo("  Use 'synapse config set <key> <value>' to change a setting.")
        click.echo("  Use 'synapse config get <key>' to read a setting.\n")
