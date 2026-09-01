"""Click commands for `synapse transcript`."""
from __future__ import annotations

import sys

import click


@click.group("transcript")
def transcript_group() -> None:
    """Read and search agent conversation transcripts."""
    pass


@transcript_group.command("read")
@click.argument("path", type=click.Path(exists=True))
@click.option("--tool", default=None, help="Tool that produced the transcript (auto-detected if omitted).")
@click.option("--limit", default=20, help="Maximum exchanges to show.")
@click.pass_context
def transcript_read(ctx: click.Context, path: str, tool: str | None, limit: int) -> None:
    """Read and display a transcript file."""
    from pathlib import Path
    from ...transcript.reader import read_transcript

    transcript = read_transcript(Path(path), tool)

    click.echo(f"\n  Transcript: {transcript.tool}")
    if transcript.session_id:
        click.echo(f"  Session: {transcript.session_id}")
    click.echo(f"  Exchanges: {len(transcript.exchanges)}\n")

    for i, exchange in enumerate(transcript.exchanges[:limit]):
        role_icon = {"user": "👤", "assistant": "🤖", "tool": "🔧"}.get(exchange.role, "❓")
        role_style = {"user": "cyan", "assistant": "green", "tool": "yellow"}.get(exchange.role, "white")

        content = exchange.content[:200].replace("\n", "\n    ")
        if len(exchange.content) > 200:
            content += "..."

        click.echo(f"  {role_icon} {click.style(exchange.role, fg=role_style)}")
        if exchange.tool_name:
            click.echo(f"    tool: {exchange.tool_name}")
        click.echo(f"    {content}\n")

    if len(transcript.exchanges) > limit:
        click.echo(f"  ... and {len(transcript.exchanges) - limit} more exchanges")


@transcript_group.command("search")
@click.argument("query")
@click.option("--tool", default=None, help="Limit to a specific tool.")
@click.option("--limit", default=20, help="Maximum results.")
@click.pass_context
def transcript_search(ctx: click.Context, query: str, tool: str | None, limit: int) -> None:
    """Search across all transcripts for a text pattern."""
    from ...transcript.reader import search_transcripts

    results = search_transcripts(query, tool, max_results=limit)

    if not results:
        click.echo("  No results found.")
        return

    click.echo(f"\n  Found {len(results)} match(es):\n")
    for r in results:
        click.echo(
            f"  {click.style(r['tool'], fg='cyan')} "
            f"{click.style(r['path'], fg='dim')}"
        )
        click.echo(f"    [{r['role']}] {r['content_preview'][:120]}")
        click.echo()


@transcript_group.command("list")
@click.option("--tool", default=None, help="Filter by tool.")
@click.option("--limit", default=20, help="Maximum transcripts to show.")
@click.pass_context
def transcript_list(ctx: click.Context, tool: str | None, limit: int) -> None:
    """List available transcript files."""
    from pathlib import Path
    from ...transcript.reader import (
        _claude_transcript_dir, _gemini_transcript_dir,
        _codex_transcript_dir, _cursor_transcript_dir,
    )

    dirs = []
    if tool is None or tool == "claude":
        dirs.append(("claude", _claude_transcript_dir()))
    if tool is None or tool == "gemini":
        dirs.append(("gemini", _gemini_transcript_dir()))
    if tool is None or tool == "codex":
        dirs.append(("codex", _codex_transcript_dir()))
    if tool is None or tool == "cursor":
        dirs.append(("cursor", _cursor_transcript_dir()))

    count = 0
    for tool_name, dir_path in dirs:
        if not dir_path.exists():
            continue
        for file_path in sorted(dir_path.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
            if count >= limit:
                break
            size_kb = file_path.stat().st_size / 1024
            click.echo(
                f"  {click.style(tool_name, fg='cyan')}  "
                f"{file_path.name}  "
                f"({size_kb:.1f} KB)"
            )
            count += 1

    if count == 0:
        click.echo("  No transcripts found.")
