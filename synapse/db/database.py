"""Thread-safe SQLite database wrapper for Synapse (WAL mode, migrations)."""

import sqlite3
import threading
import time
from pathlib import Path

from .schema import SCHEMA_SQL, SCHEMA_VERSION, FTS_SQL


class Database:
    """Thin wrapper around SQLite with WAL mode, FK enforcement, and schema migrations.

    One ``Database`` instance is safe to share across threads; each thread
    receives its own ``sqlite3.Connection`` via thread-local storage so that
    concurrent reads never block each other and WAL write serialisation is
    handled by SQLite itself.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)

        self._local = threading.local()

        # Apply schema on the calling thread's connection so that the database
        # is fully initialised before any other code interacts with it.
        conn = self._open_connection()
        self._apply_schema(conn)

    # ──────────────────────────────────────────────────────────────
    # Connection management
    # ──────────────────────────────────────────────────────────────

    def _open_connection(self) -> sqlite3.Connection:
        """Open a new SQLite connection with all required pragmas applied."""
        conn = sqlite3.connect(
            self.path,
            check_same_thread=False,  # we manage thread-safety ourselves
            isolation_level=None,     # autocommit; we use explicit BEGIN where needed
        )
        conn.row_factory = sqlite3.Row

        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=NORMAL")  # safe with WAL; faster than FULL
        conn.execute("PRAGMA busy_timeout=5000")   # wait up to 5 s on lock contention

        return conn

    def connect(self) -> sqlite3.Connection:
        """Return the thread-local :class:`sqlite3.Connection`, opening one if needed."""
        conn: sqlite3.Connection | None = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._open_connection()
            self._local.conn = conn
        return conn

    # ──────────────────────────────────────────────────────────────
    # Convenience query helpers
    # ──────────────────────────────────────────────────────────────

    def execute(self, sql: str, params: tuple | list = ()) -> sqlite3.Cursor:
        """Execute *sql* with *params* and return the cursor."""
        return self.connect().execute(sql, params)

    def executemany(self, sql: str, params: list[tuple]) -> sqlite3.Cursor:
        """Execute *sql* once per item in *params* and return the cursor."""
        return self.connect().executemany(sql, params)

    def fetchone(self, sql: str, params: tuple | list = ()) -> sqlite3.Row | None:
        """Return the first row matching *sql*, or ``None``."""
        return self.connect().execute(sql, params).fetchone()

    def fetchall(self, sql: str, params: tuple | list = ()) -> list[sqlite3.Row]:
        """Return all rows matching *sql*."""
        return self.connect().execute(sql, params).fetchall()

    # ──────────────────────────────────────────────────────────────
    # Time helper
    # ──────────────────────────────────────────────────────────────

    @staticmethod
    def now_ms() -> int:
        """Return the current UTC time as epoch milliseconds."""
        return int(time.time() * 1000)

    # ──────────────────────────────────────────────────────────────
    # Schema bootstrap & migration
    # ──────────────────────────────────────────────────────────────

    def _apply_schema(self, conn: sqlite3.Connection) -> None:
        """Create all tables/indexes and advance ``user_version`` if necessary.

        The migration strategy is intentionally simple for v0.x:
        - ``user_version == 0`` → fresh database; apply full schema.
        - ``user_version == SCHEMA_VERSION`` → nothing to do.
        - Lower version → run incremental migrations (add cases here as the
          schema evolves).
        """
        current_version: int = conn.execute("PRAGMA user_version").fetchone()[0]

        if current_version == SCHEMA_VERSION:
            return

        # Apply the baseline schema (idempotent — all statements use
        # CREATE ... IF NOT EXISTS).
        conn.executescript(SCHEMA_SQL)
        conn.executescript(FTS_SQL)

        if current_version < SCHEMA_VERSION:
            # Placeholder for future incremental migrations:
            # if current_version < 2: conn.executescript(MIGRATION_V2_SQL)
            pass

        # Stamp the new version.  PRAGMA user_version cannot be parameterised.
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    # ──────────────────────────────────────────────────────────────
    # Context manager support
    # ──────────────────────────────────────────────────────────────

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the calling thread's connection, if open."""
        conn: sqlite3.Connection | None = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None
