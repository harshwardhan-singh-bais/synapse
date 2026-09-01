"""
Output formatting utilities for CLI commands.

Provides --json, --pretty, --text, and --toon output format support.
"""
from __future__ import annotations

import json
import sys
from typing import Any, Optional

import click


def format_output(
    data: Any,
    fmt: str = "text",
    indent: int = 2,
) -> str:
    """Format *data* according to the output format *fmt*.

    - ``text`` — human-readable plain text (default).
    - ``json`` — compact JSON.
    - ``pretty`` — pretty-printed JSON with indentation.
    - ``toon`` — compact tree-like output (Thurbox Object Notation).
    """
    if fmt == "json":
        return json.dumps(data, default=str, separators=(",", ":"))
    elif fmt == "pretty":
        return json.dumps(data, default=str, indent=indent)
    elif fmt == "toon":
        return _format_toon(data)
    else:
        # text format — default human-readable
        if isinstance(data, dict):
            lines: list[str] = []
            for key, value in data.items():
                if isinstance(value, list):
                    lines.append(f"{key}:")
                    for item in value:
                        lines.append(f"  - {item}")
                elif isinstance(value, dict):
                    lines.append(f"{key}:")
                    for k, v in value.items():
                        lines.append(f"  {k}: {v}")
                else:
                    lines.append(f"{key}: {value}")
            return "\n".join(lines)
        elif isinstance(data, list):
            if not data:
                return "(empty)"
            lines = []
            for item in data:
                if isinstance(item, dict):
                    # Compact one-line representation
                    parts = [f"{k}={v}" for k, v in item.items()]
                    lines.append("  ".join(parts))
                else:
                    lines.append(f"  {item}")
            return "\n".join(lines)
        else:
            return str(data)


def _format_toon(data: Any, depth: int = 0) -> str:
    """Format data as TOON (Thurbox Object Notation).

    TOON is a compact, tree-like format:
    - Objects: key=value pairs, one per line
    - Arrays: items prefixed with ``-``
    - Nested structures use indentation (2 spaces per level)
    - Strings are unquoted unless they contain special characters
    - Numbers and booleans are bare
    - null is represented as ``~``

    Example::

        session:
          name=feature-auth
          status=working
          tags:
            - backend
            - api
    """
    if data is None:
        return "~"
    elif isinstance(data, bool):
        return "true" if data else "false"
    elif isinstance(data, (int, float)):
        return str(data)
    elif isinstance(data, str):
        # Quote strings that contain spaces, newlines, or special chars
        if any(c in data for c in (" ", "\n", "\t", "=", ":", ",", "{", "}", "[", "]", "~")):
            escaped = data.replace("\\", "\\\\").replace('"', '\\"')
            return f'"{escaped}"'
        return data
    elif isinstance(data, dict):
        if not data:
            return "{}"
        lines: list[str] = []
        prefix = "  " * depth
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                lines.append(f"{prefix}{key}:")
                lines.append(_format_toon(value, depth + 1))
            else:
                lines.append(f"{prefix}{key}={_format_toon(value, depth + 1)}")
        return "\n".join(lines)
    elif isinstance(data, list):
        if not data:
            return "[]"
        lines: list[str] = []
        prefix = "  " * depth
        for item in data:
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}-")
                lines.append(_format_toon(item, depth + 1))
            else:
                lines.append(f"{prefix}- {_format_toon(item, depth)}")
        return "\n".join(lines)
    else:
        return str(data)


def output_option(func: Any = None) -> Any:
    """Decorator that adds --json/--pretty/--text/--toon output format options."""

    def decorator(f: Any) -> Any:
        f = click.option("--json", "output_format", flag_value="json", help="Output as JSON.")(f)
        f = click.option("--pretty", "output_format", flag_value="pretty", help="Output as pretty JSON.")(f)
        f = click.option("--toon", "output_format", flag_value="toon", help="Output as TOON (tree format).")(f)
        f = click.option("--text", "output_format", flag_value="text", default=True, help="Output as text (default).")(f)
        return f

    if func is not None:
        return decorator(func)
    return decorator


def echo_output(data: Any, fmt: str = "text", **kwargs: Any) -> None:
    """Format *data* and echo it to stdout."""
    formatted = format_output(data, fmt)
    click.echo(formatted, **kwargs)


class OutputContext:
    """Context manager that captures output and formats it at the end."""

    def __init__(self, fmt: str = "text") -> None:
        self.fmt = fmt
        self._data: list[Any] = []

    def add(self, data: Any) -> None:
        self._data.append(data)

    def echo(self) -> None:
        if self.fmt in ("json", "pretty"):
            # Combine all data into a single JSON output
            combined = self._data[0] if len(self._data) == 1 else self._data
            echo_output(combined, self.fmt)
        else:
            for item in self._data:
                echo_output(item, self.fmt)
