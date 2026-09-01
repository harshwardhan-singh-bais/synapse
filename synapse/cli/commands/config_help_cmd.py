"""Click command for `synapse config help`."""
from __future__ import annotations

import click


CONFIG_DOCS = {
    "db_path": "Path to the SQLite database file. Default: ~/.local/share/synapse/synapse.db",
    "default_agent": "Default agent to use when creating sessions. Default: claude",
    "effort": "Orchestration effort level: low/standard/high/max. Default: standard",
    "terminal": "Terminal preset for launching agents: tmux/kitty/wezterm/iterm/alacritty/ghostty. Default: tmux",
    "relay_enabled": "Enable MQTT cross-device relay. Default: false",
    "relay_url": "MQTT broker URL for relay. e.g. mqtt://broker.emqx.io:1883",
    "max_parallel": "Maximum parallel orchestration stages. Default: 2",
    "audit_retention_days": "Days to keep audit log entries. Default: 30",
    "timeout": "Idle timeout for non-PTY instances (seconds). Default: 86400",
    "subagent_timeout": "Timeout for subagent processes (seconds). Default: 30",
    "hints": "Extra context appended to messages sent to agents.",
    "tag": "Group tag for launched agents. Alphanumeric + hyphens only.",
    "auto_subscribe": "Auto-subscription presets (comma-separated). Default: collision",
    "auto_approve": "Auto-approve agent actions. Default: true",
    "auto_trust_workspace": "Auto-trust workspace on first use. Default: false",
    "title_mode": "Terminal title behavior: combined/label/off. Default: combined",
    "claude_args": "Extra arguments for Claude launches.",
    "gemini_args": "Extra arguments for Gemini launches.",
    "codex_args": "Extra arguments for Codex launches.",
    "cursor_args": "Extra arguments for Cursor launches.",
    "codex_sandbox_mode": "Codex sandbox mode: workspace/untrusted/danger-full-access/none. Default: workspace",
    "per_agent_system_prompts": "Per-agent system prompt overrides. Set in agents.toml as system_prompt field.",
    "per_agent_launch_args": "Per-agent launch argument overrides. Set in agents.toml as launch_args field.",
}


@click.command("help")
@click.argument("key", required=False)
@click.pass_context
def config_help(ctx: click.Context, key: str | None) -> None:
    """Show help for configuration keys.

    If KEY is provided, shows help for that specific key.
    Without an argument, lists all available keys.
    """
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
