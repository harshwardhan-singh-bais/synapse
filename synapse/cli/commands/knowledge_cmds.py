"""Click commands for `synapse knowledge`."""
from __future__ import annotations

import sys
from typing import Optional

import click

from ...core.config import SynapseConfig
from ...db.database import Database
from ...knowledge.artifacts import ArtifactStore, compute_python


def _get_store(ctx: click.Context) -> ArtifactStore:
    config: SynapseConfig = ctx.obj["config"]
    db = Database(config.db_path)
    return ArtifactStore(db)


@click.group("knowledge")
def knowledge_group() -> None:
    """Manage knowledge artifacts and run compute expressions."""
    pass


@knowledge_group.command("write")
@click.argument("key")
@click.option("--file", "filepath", default=None, help="Read content from a file.")
@click.option("--content", default=None, help="Content to write.")
@click.option("--name", default=None, help="Human-readable name.")
@click.option("--mime", "mime_type", default=None, help="MIME type (e.g. text/markdown).")
@click.pass_context
def knowledge_write(ctx: click.Context, key: str, filepath: Optional[str],
                    content: Optional[str], name: Optional[str],
                    mime_type: Optional[str]) -> None:
    """Write (upsert) a knowledge artifact."""
    store = _get_store(ctx)

    if filepath:
        from pathlib import Path
        p = Path(filepath)
        if not p.exists():
            click.echo(click.style(f"File '{filepath}' not found.", fg="red"), err=True)
            sys.exit(1)
        content = p.read_text(encoding="utf-8")
        if mime_type is None:
            suffix = p.suffix.lower()
            mime_map = {".md": "text/markdown", ".json": "application/json",
                        ".yaml": "text/yaml", ".toml": "text/toml",
                        ".py": "text/x-python", ".txt": "text/plain"}
            mime_type = mime_map.get(suffix, "text/plain")

    if content is None:
        # Read from stdin
        click.echo("  Enter content (Ctrl+D to finish):")
        content = sys.stdin.read()

    artifact = store.write(key, content, name=name, mime_type=mime_type)
    click.echo(
        click.style("✓", fg="green")
        + f" Artifact '{click.style(key, bold=True)}' written"
        + f" ({len(content)} bytes, id={artifact.id})"
    )


@knowledge_group.command("read")
@click.argument("key")
@click.option("--raw", is_flag=True, help="Print content only, no formatting.")
@click.pass_context
def knowledge_read(ctx: click.Context, key: str, raw: bool) -> None:
    """Read a knowledge artifact."""
    store = _get_store(ctx)
    artifact = store.read(key)

    if artifact is None:
        click.echo(click.style(f"Artifact '{key}' not found.", fg="red"), err=True)
        sys.exit(1)

    if raw:
        click.echo(artifact.content or "")
    else:
        click.echo(f"\n  {click.style(artifact.key, fg='cyan', bold=True)}")
        if artifact.name and artifact.name != artifact.key:
            click.echo(f"  name:      {artifact.name}")
        if artifact.mime_type:
            click.echo(f"  mime:      {artifact.mime_type}")
        if artifact.content:
            content = artifact.content
            if len(content) > 500:
                content = content[:500] + f"\n  ... ({len(artifact.content)} total chars)"
            click.echo(f"  content:\n    {content.replace(chr(10), chr(10) + '    ')}")
        click.echo()


@knowledge_group.command("list")
@click.option("--prefix", default=None, help="Filter by key prefix.")
@click.option("--limit", default=50, show_default=True, help="Max artifacts to show.")
@click.pass_context
def knowledge_list(ctx: click.Context, prefix: Optional[str], limit: int) -> None:
    """List knowledge artifacts."""
    store = _get_store(ctx)
    artifacts = store.list_artifacts(prefix=prefix, limit=limit)

    if not artifacts:
        click.echo("No artifacts found.")
        return

    click.echo(f"\n  {len(artifact for artifact in artifacts)} artifact(s):\n")
    for a in artifacts:
        size = len(a.content) if a.content else 0
        mime = a.mime_type or ""
        click.echo(
            f"    {click.style(a.key, fg='cyan'):<30} "
            f"{mime:<20} "
            f"{size:>8} bytes"
        )
    click.echo()


@knowledge_group.command("delete")
@click.argument("key")
@click.option("--yes", is_flag=True, help="Skip confirmation.")
@click.pass_context
def knowledge_delete(ctx: click.Context, key: str, yes: bool) -> None:
    """Delete a knowledge artifact."""
    store = _get_store(ctx)

    if not store.exists(key):
        click.echo(click.style(f"Artifact '{key}' not found.", fg="red"), err=True)
        sys.exit(1)

    if not yes:
        if not click.confirm(f"Delete artifact '{key}'?"):
            click.echo("Cancelled.")
            return

    store.delete(key)
    click.echo(click.style("✓", fg="green") + f" Artifact '{key}' deleted.")


@knowledge_group.command("compute")
@click.argument("expression")
@click.option("--timeout", default=5.0, show_default=True, help="Timeout in seconds.")
@click.pass_context
def knowledge_compute(ctx: click.Context, expression: str, timeout: float) -> None:
    """Safely evaluate a Python expression.

    EXAMPLES:
        synapse knowledge compute "1 + 2"
        synapse knowledge compute "len([1, 2, 3, 4, 5])"
        synapse knowledge compute "max(10, 20, 30)"
    """
    result = compute_python(expression, timeout=timeout)
    click.echo(result)
