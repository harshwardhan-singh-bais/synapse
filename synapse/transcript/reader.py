"""
Transcript reader — parses agent conversation transcripts from various tools.

Supports: Claude, Gemini, Codex, Cursor, Kimi, OpenCode.
Each tool stores transcripts in a different format and location.
"""
from __future__ import annotations

import gzip
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class Exchange:
    """A single exchange (turn) in a conversation."""
    role: str  # 'user' | 'assistant' | 'tool'
    content: str
    timestamp: Optional[str] = None
    tool_name: Optional[str] = None
    tool_input: Optional[dict[str, Any]] = None
    tool_output: Optional[str] = None
    thinking: Optional[str] = None
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None


@dataclass
class Transcript:
    """A parsed conversation transcript."""
    tool: str
    session_id: Optional[str] = None
    exchanges: list[Exchange] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────────────
# Tool-specific transcript paths
# ──────────────────────────────────────────────────────────────────────────────


def _claude_transcript_dir() -> Path:
    return Path.home() / ".claude" / "projects"


def _gemini_transcript_dir() -> Path:
    return Path.home() / ".gemini" / "sessions"


def _codex_transcript_dir() -> Path:
    return Path.home() / ".codex" / "sessions"


def _cursor_transcript_dir() -> Path:
    return Path.home() / ".cursor" / "sessions"


# ──────────────────────────────────────────────────────────────────────────────
# Claude transcript reader
# ──────────────────────────────────────────────────────────────────────────────


def read_claude_transcript(path: Path) -> Transcript:
    """Read a Claude conversation transcript (JSONL format)."""
    transcript = Transcript(tool="claude")
    lines = _read_file_lines(path)

    for line in lines:
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue

        msg_type = entry.get("type", "")

        if msg_type == "human":
            content = _extract_text(entry.get("message", {}))
            transcript.exchanges.append(Exchange(role="user", content=content))
        elif msg_type == "assistant":
            message = entry.get("message", {})
            content = _extract_text(message)
            thinking = None

            # Extract thinking blocks
            for block in message.get("content", []):
                if isinstance(block, dict) and block.get("type") == "thinking":
                    thinking = block.get("thinking", "")

            transcript.exchanges.append(
                Exchange(role="assistant", content=content, thinking=thinking)
            )
        elif msg_type == "tool_use":
            tool_name = entry.get("name", "")
            tool_input = entry.get("input", {})
            transcript.exchanges.append(
                Exchange(
                    role="tool",
                    content="",
                    tool_name=tool_name,
                    tool_input=tool_input,
                )
            )
        elif msg_type == "tool_result":
            content = entry.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    b.get("text", "") for b in content if isinstance(b, dict)
                )
            transcript.exchanges.append(
                Exchange(role="tool", content=str(content))
            )

    return transcript


# ──────────────────────────────────────────────────────────────────────────────
# Gemini transcript reader
# ──────────────────────────────────────────────────────────────────────────────


def read_gemini_transcript(path: Path) -> Transcript:
    """Read a Gemini conversation transcript (JSONL format)."""
    transcript = Transcript(tool="gemini")
    lines = _read_file_lines(path)

    for line in lines:
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue

        role = entry.get("role", "")
        content = entry.get("content", "")

        if role in ("user", "model"):
            transcript.exchanges.append(
                Exchange(role="user" if role == "user" else "assistant", content=str(content))
            )

    return transcript


# ──────────────────────────────────────────────────────────────────────────────
# Codex transcript reader
# ──────────────────────────────────────────────────────────────────────────────


def read_codex_transcript(path: Path) -> Transcript:
    """Read a Codex conversation transcript (JSONL format)."""
    transcript = Transcript(tool="codex")
    lines = _read_file_lines(path)

    for line in lines:
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue

        role = entry.get("type", "")
        content = entry.get("text", "")

        if role == "message":
            transcript.exchanges.append(
                Exchange(role="assistant", content=str(content))
            )
        elif role == "function":
            transcript.exchanges.append(
                Exchange(
                    role="tool",
                    content=str(content),
                    tool_name=entry.get("name"),
                )
            )

    return transcript


# ──────────────────────────────────────────────────────────────────────────────
# Cursor transcript reader
# ──────────────────────────────────────────────────────────────────────────────


def read_cursor_transcript(path: Path) -> Transcript:
    """Read a Cursor conversation transcript (JSONL format)."""
    transcript = Transcript(tool="cursor")
    lines = _read_file_lines(path)

    for line in lines:
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue

        role = entry.get("role", "")
        content = entry.get("content", "")

        if role in ("user", "assistant"):
            transcript.exchanges.append(Exchange(role=role, content=str(content)))

    return transcript


# ──────────────────────────────────────────────────────────────────────────────
# Kimi transcript reader
# ──────────────────────────────────────────────────────────────────────────────


def _kimi_transcript_dir() -> Path:
    return Path.home() / ".kimi" / "sessions"


def read_kimi_transcript(path: Path) -> Transcript:
    """Read a Kimi conversation transcript (JSONL format).

    Kimi stores transcripts with a 'messages' array containing role/content pairs.
    """
    transcript = Transcript(tool="kimi")
    lines = _read_file_lines(path)

    for line in lines:
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue

        # Kimi may use a 'messages' array inside each line
        if "messages" in entry and isinstance(entry["messages"], list):
            for msg in entry["messages"]:
                role = msg.get("role", "")
                content = msg.get("content", "")
                if role in ("user", "assistant"):
                    transcript.exchanges.append(
                        Exchange(role=role, content=str(content))
                    )
            continue

        # Or flat role/content fields
        role = entry.get("role", "")
        content = entry.get("content", "")
        if role in ("user", "assistant"):
            transcript.exchanges.append(
                Exchange(role=role, content=str(content))
            )

    return transcript


# ──────────────────────────────────────────────────────────────────────────────
# OpenCode transcript reader
# ──────────────────────────────────────────────────────────────────────────────


def _opencode_transcript_dir() -> Path:
    return Path.home() / ".opencode" / "sessions"


def read_opencode_transcript(path: Path) -> Transcript:
    """Read an OpenCode conversation transcript (JSONL format)."""
    transcript = Transcript(tool="opencode")
    lines = _read_file_lines(path)

    for line in lines:
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue

        role = entry.get("role", "")
        content = entry.get("content", "")
        if role in ("user", "assistant", "system"):
            transcript.exchanges.append(
                Exchange(role=role if role != "system" else "user", content=str(content))
            )

    return transcript


# ──────────────────────────────────────────────────────────────────────────────
# Unified reader
# ──────────────────────────────────────────────────────────────────────────────


_TOOL_READERS = {
    "claude": read_claude_transcript,
    "gemini": read_gemini_transcript,
    "codex": read_codex_transcript,
    "cursor": read_cursor_transcript,
    "kimi": read_kimi_transcript,
    "opencode": read_opencode_transcript,
}


def read_transcript(path: Path, tool: Optional[str] = None) -> Transcript:
    """Read a transcript file, auto-detecting the tool if not specified."""
    if tool is None:
        tool = _detect_tool_from_path(str(path))

    reader = _TOOL_READERS.get(tool)
    if reader is None:
        return Transcript(tool=tool or "unknown", metadata={"path": str(path)})

    return reader(path)


def detect_tool_from_path(path: str) -> Optional[str]:
    """Detect which tool produced a transcript from its file path."""
    return _detect_tool_from_path(path)


def _detect_tool_from_path(path: str) -> Optional[str]:
    lower = path.lower()
    if ".claude" in lower or "claude" in lower:
        return "claude"
    if ".gemini" in lower or "gemini" in lower:
        return "gemini"
    if ".codex" in lower or "codex" in lower:
        return "codex"
    if ".cursor" in lower or "cursor" in lower:
        return "cursor"
    if ".kimi" in lower or "kimi" in lower:
        return "kimi"
    if "opencode" in lower:
        return "opencode"
    return None


def search_transcripts(
    query: str,
    tool: Optional[str] = None,
    max_results: int = 50,
) -> list[dict[str, Any]]:
    """Search across all transcripts for a text pattern."""
    results: list[dict[str, Any]] = []

    dirs = []
    if tool is None or tool == "claude":
        dirs.append(("claude", _claude_transcript_dir()))
    if tool is None or tool == "gemini":
        dirs.append(("gemini", _gemini_transcript_dir()))
    if tool is None or tool == "codex":
        dirs.append(("codex", _codex_transcript_dir()))
    if tool is None or tool == "cursor":
        dirs.append(("cursor", _cursor_transcript_dir()))
    if tool is None or tool == "kimi":
        dirs.append(("kimi", _kimi_transcript_dir()))
    if tool is None or tool == "opencode":
        dirs.append(("opencode", _opencode_transcript_dir()))

    for tool_name, dir_path in dirs:
        if not dir_path.exists():
            continue
        for file_path in dir_path.rglob("*.jsonl"):
            if len(results) >= max_results:
                break
            try:
                transcript = read_transcript(file_path, tool_name)
                for i, exchange in enumerate(transcript.exchanges):
                    if query.lower() in exchange.content.lower():
                        results.append({
                            "tool": tool_name,
                            "path": str(file_path),
                            "exchange_index": i,
                            "role": exchange.role,
                            "content_preview": exchange.content[:200],
                        })
                        if len(results) >= max_results:
                            break
            except Exception:
                continue

    return results


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _read_file_lines(path: Path) -> list[str]:
    """Read lines from a file, handling gzip compression."""
    if not path.exists():
        return []

    if path.suffix == ".gz":
        try:
            with gzip.open(path, "rt", encoding="utf-8", errors="replace") as f:
                return f.readlines()
        except Exception:
            return []

    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []


def _extract_text(message: dict[str, Any]) -> str:
    """Extract text content from a message dict."""
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return str(content)
