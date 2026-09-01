"""
Knowledge artifacts — read/write/list storage for knowledge system artifacts.

Provides a simple key-value artifact store backed by the knowledge_artifacts
table in SQLite, plus a safe compute tool for running Python expressions.
"""
from __future__ import annotations

import ast
import io
import logging
import sys
import time
from contextlib import redirect_stdout, redirect_stderr
from dataclasses import dataclass
from typing import Any, Optional

from ..db.database import Database

log = logging.getLogger(__name__)


@dataclass
class Artifact:
    """A single knowledge artifact."""
    id: int
    key: str
    name: Optional[str] = None
    content: Optional[str] = None
    mime_type: Optional[str] = None
    created_at: Optional[int] = None
    updated_at: Optional[int] = None


class ArtifactStore:
    """CRUD operations for knowledge artifacts stored in SQLite."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def write(self, key: str, content: str, name: Optional[str] = None,
              mime_type: Optional[str] = None) -> Artifact:
        """Write (upsert) an artifact by key. Returns the artifact."""
        now = self.db.now_ms()
        existing = self.db.fetchone(
            "SELECT id FROM knowledge_artifacts WHERE key=?", (key,)
        )
        if existing:
            self.db.execute(
                """UPDATE knowledge_artifacts
                   SET content=?, name=?, mime_type=?, updated_at=?
                   WHERE key=?""",
                (content, name or key, mime_type, now, key),
            )
            row = self.db.fetchone(
                "SELECT * FROM knowledge_artifacts WHERE key=?", (key,)
            )
        else:
            cur = self.db.execute(
                """INSERT INTO knowledge_artifacts
                   (key, name, content, mime_type, created_at, updated_at)
                   VALUES (?,?,?,?,?,?)""",
                (key, name or key, content, mime_type, now, now),
            )
            row = self.db.fetchone(
                "SELECT * FROM knowledge_artifacts WHERE id=?",
                (cur.lastrowid,),
            )
        return self._row_to_artifact(row) if row else Artifact(id=0, key=key)

    def read(self, key: str) -> Optional[Artifact]:
        """Read an artifact by key. Returns None if not found."""
        row = self.db.fetchone(
            "SELECT * FROM knowledge_artifacts WHERE key=?", (key,)
        )
        return self._row_to_artifact(row) if row else None

    def list_artifacts(self, prefix: Optional[str] = None,
                       limit: int = 100) -> list[Artifact]:
        """List artifacts, optionally filtered by key prefix."""
        if prefix:
            rows = self.db.fetchall(
                "SELECT * FROM knowledge_artifacts WHERE key LIKE ? ORDER BY updated_at DESC LIMIT ?",
                (f"{prefix}%", limit),
            )
        else:
            rows = self.db.fetchall(
                "SELECT * FROM knowledge_artifacts ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            )
        return [self._row_to_artifact(r) for r in rows]

    def delete(self, key: str) -> bool:
        """Delete an artifact by key. Returns True if it existed."""
        row = self.db.fetchone(
            "SELECT id FROM knowledge_artifacts WHERE key=?", (key,)
        )
        if row:
            self.db.execute("DELETE FROM knowledge_artifacts WHERE key=?", (key,))
            return True
        return False

    def exists(self, key: str) -> bool:
        """Check if an artifact with the given key exists."""
        row = self.db.fetchone(
            "SELECT 1 FROM knowledge_artifacts WHERE key=?", (key,)
        )
        return row is not None

    def count(self, prefix: Optional[str] = None) -> int:
        """Count artifacts, optionally filtered by key prefix."""
        if prefix:
            row = self.db.fetchone(
                "SELECT COUNT(*) as c FROM knowledge_artifacts WHERE key LIKE ?",
                (f"{prefix}%",),
            )
        else:
            row = self.db.fetchone(
                "SELECT COUNT(*) as c FROM knowledge_artifacts"
            )
        return row["c"] if row else 0

    @staticmethod
    def _row_to_artifact(row: object) -> Artifact:
        d = dict(row)  # type: ignore[arg-type]
        return Artifact(
            id=d["id"],
            key=d["key"],
            name=d.get("name"),
            content=d.get("content"),
            mime_type=d.get("mime_type"),
            created_at=d.get("created_at"),
            updated_at=d.get("updated_at"),
        )


# ──────────────────────────────────────────────────────────────────────────────
# Compute tool — safe Python evaluation
# ──────────────────────────────────────────────────────────────────────────────

# Builtins that are safe to expose in the compute sandbox
_SAFE_BUILTINS = {
    "abs", "all", "any", "bin", "bool", "bytearray", "bytes",
    "callable", "chr", "divmod", "enumerate", "filter", "float",
    "format", "frozenset", "getattr", "hasattr", "hash", "hex",
    "id", "int", "isinstance", "issubclass", "iter", "len",
    "list", "map", "max", "min", "next", "oct", "ord", "pow",
    "print", "range", "repr", "reversed", "round", "set",
    "slice", "sorted", "str", "sum", "tuple", "type", "zip",
}


def compute_python(expression: str, timeout: float = 5.0) -> str:
    """Safely evaluate a Python expression and return its string representation.

    The evaluation is sandboxed:
    - Only safe builtins are available (no __import__, eval, exec, open, etc.)
    - Execution is bounded by *timeout* seconds.
    - stdout/stderr are captured.

    Returns the result as a string, or an error message prefixed with "[Error]".
    """
    import signal

    # Parse the expression to check for dangerous constructs
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError:
        # Try as a statement (for assignments, loops, etc.)
        try:
            tree = ast.parse(expression, mode="exec")
        except SyntaxError as exc:
            return f"[Error] Syntax error: {exc}"

    # Check for dangerous nodes
    dangerous = {"Import", "ImportFrom", "Delete", "Global", "Nonlocal"}
    for node in ast.walk(tree):
        if type(node).__name__ in dangerous:
            return f"[Error] Forbidden construct: {type(node).__name__}"

    # Set up a restricted globals
    restricted_globals: dict[str, Any] = {"__builtins__": {}}
    for name in _SAFE_BUILTINS:
        if hasattr(__builtins__, name):  # type: ignore[union-attr]
            restricted_globals["__builtins__"][name] = getattr(__builtins__, name)  # type: ignore[union-attr]

    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()

    def _timeout_handler(signum: int, frame: Any) -> None:
        raise TimeoutError("Compute expression timed out")

    old_handler = signal.signal(signal.SIGALRM, _timeout_handler)  # type: ignore[arg-type]
    signal.setitimer(signal.ITIMER_REAL, timeout)

    try:
        with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
            result = eval(compile(tree, "<compute>", "eval"), restricted_globals)  # noqa: S307
        output = stdout_buf.getvalue()
        if output:
            return output + "\n" + repr(result)
        return repr(result)
    except TimeoutError:
        return "[Error] Compute expression timed out"
    except Exception as exc:
        stderr_output = stderr_buf.getvalue()
        if stderr_output:
            return f"[Error] {stderr_output.strip()}"
        return f"[Error] {type(exc).__name__}: {exc}"
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_handler)
