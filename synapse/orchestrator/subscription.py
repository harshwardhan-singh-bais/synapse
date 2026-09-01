"""
Subscription manager — manages API key pools and rotation for LLM providers.

Handles ANTHROPIC_API_KEY (and other provider keys) as a pool that can be
rotated when rate limits are hit.  Keys are stored in the DB and popped
in round-robin or least-recently-used order.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Optional

from ..db.database import Database

log = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# API Key entry
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class ApiKeyEntry:
    """A single API key in the subscription pool."""
    id: int
    provider: str  # "anthropic", "openai", "google"
    key_hint: str  # last 4 chars for display
    created_at: int
    last_used_at: Optional[int] = None
    last_error_at: Optional[int] = None
    error_count: int = 0
    is_active: bool = True
    label: Optional[str] = None  # user-friendly label


# ──────────────────────────────────────────────────────────────────────────────
# Subscription manager
# ──────────────────────────────────────────────────────────────────────────────


class SubscriptionManager:
    """Manages a pool of API keys with rotation and error tracking.

    Keys are stored in the ``api_keys`` table in SQLite.  The manager
    provides:
    - Add/remove keys
    - Pop the next available key (round-robin with error avoidance)
    - Mark keys as failed (temporarily or permanently)
    - Auto-fallback to env vars if no keys in DB
    """

    def __init__(self, db: Database) -> None:
        self.db = db
        self._ensure_table()

    def _ensure_table(self) -> None:
        """Create the api_keys table if it doesn't exist."""
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS api_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider TEXT NOT NULL,
                key_value TEXT NOT NULL,
                key_hint TEXT NOT NULL,
                label TEXT,
                created_at INTEGER NOT NULL,
                last_used_at INTEGER,
                last_error_at INTEGER,
                error_count INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1
            )
        """)
        # Create index for fast provider lookups
        self.db.execute("""
            CREATE INDEX IF NOT EXISTS idx_api_keys_provider
            ON api_keys(provider, is_active)
        """)

    # ──────────────────────────────────────────────────────────────────────────
    # Key management
    # ──────────────────────────────────────────────────────────────────────────

    def add_key(
        self,
        provider: str,
        key: str,
        label: Optional[str] = None,
    ) -> ApiKeyEntry:
        """Add an API key to the pool."""
        now = int(time.time() * 1000)
        key_hint = key[-4:] if len(key) >= 4 else key

        cur = self.db.execute(
            """INSERT INTO api_keys
               (provider, key_value, key_hint, label, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (provider, key, key_hint, label, now),
        )

        log.info("Added %s API key ...%s (id=%d)", provider, key_hint, cur.lastrowid)

        return ApiKeyEntry(
            id=cur.lastrowid,
            provider=provider,
            key_hint=key_hint,
            created_at=now,
            label=label,
        )

    def remove_key(self, key_id: int) -> bool:
        """Remove an API key from the pool."""
        row = self.db.fetchone(
            "SELECT id FROM api_keys WHERE id = ?", (key_id,)
        )
        if not row:
            return False
        self.db.execute("DELETE FROM api_keys WHERE id = ?", (key_id,))
        return True

    def list_keys(self, provider: Optional[str] = None) -> list[ApiKeyEntry]:
        """List all API keys, optionally filtered by provider."""
        if provider:
            rows = self.db.fetchall(
                """SELECT id, provider, key_hint, label, created_at,
                          last_used_at, last_error_at, error_count, is_active
                   FROM api_keys WHERE provider = ?
                   ORDER BY created_at DESC""",
                (provider,),
            )
        else:
            rows = self.db.fetchall(
                """SELECT id, provider, key_hint, label, created_at,
                          last_used_at, last_error_at, error_count, is_active
                   FROM api_keys
                   ORDER BY provider, created_at DESC"""
            )

        return [
            ApiKeyEntry(
                id=r["id"],
                provider=r["provider"],
                key_hint=r["key_hint"],
                created_at=r["created_at"],
                last_used_at=r["last_used_at"],
                last_error_at=r["last_error_at"],
                error_count=r["error_count"],
                is_active=bool(r["is_active"]),
                label=r["label"],
            )
            for r in rows
        ]

    # ──────────────────────────────────────────────────────────────────────────
    # Key rotation
    # ──────────────────────────────────────────────────────────────────────────

    def pop_key(self, provider: str) -> Optional[str]:
        """Pop the next available API key for a provider.

        Strategy:
        1. Find active keys for the provider
        2. Prefer keys with fewer errors and older last_used_at (round-robin)
        3. If no keys in DB, fall back to environment variable
        4. Returns the full key string (or None)
        """
        now = int(time.time() * 1000)

        # Try DB keys first
        rows = self.db.fetchall(
            """SELECT id, key_value, last_used_at, error_count
               FROM api_keys
               WHERE provider = ? AND is_active = 1
               ORDER BY error_count ASC, last_used_at ASC""",
            (provider,),
        )

        if rows:
            # Pick the key with fewest errors and oldest usage
            row = rows[0]
            key_id = row["id"]
            key_value = row["key_value"]

            # Update last_used_at
            self.db.execute(
                "UPDATE api_keys SET last_used_at = ? WHERE id = ?",
                (now, key_id),
            )

            log.debug("Popped %s key ...%s (id=%d)", provider, row.get("key_hint", "?"), key_id)
            return key_value

        # Fallback to environment variable
        env_key = self._get_env_key(provider)
        if env_key:
            log.debug("Using %s key from environment variable", provider)
            return env_key

        return None

    def mark_error(self, provider: str, key_hint: Optional[str] = None) -> None:
        """Mark a key as having an error (rate limit, etc.).

        If a key hits 3+ consecutive errors, it's deactivated temporarily.
        """
        now = int(time.time() * 1000)

        if key_hint:
            self.db.execute(
                """UPDATE api_keys
                   SET last_error_at = ?, error_count = error_count + 1
                   WHERE provider = ? AND key_hint = ?""",
                (now, provider, key_hint),
            )
            # Deactivate if too many errors
            self.db.execute(
                """UPDATE api_keys
                   SET is_active = 0
                   WHERE provider = ? AND key_hint = ? AND error_count >= 3""",
                (provider, key_hint),
            )
        else:
            # Mark the most recently used key as errored
            self.db.execute(
                """UPDATE api_keys
                   SET last_error_at = ?, error_count = error_count + 1
                   WHERE provider = ? AND is_active = 1
                   ORDER BY last_used_at DESC LIMIT 1""",
                (now, provider),
            )

    def reset_errors(self, provider: Optional[str] = None) -> int:
        """Reset error counts and reactivate all keys.

        Returns the number of keys reactivated.
        """
        if provider:
            result = self.db.execute(
                """UPDATE api_keys
                   SET error_count = 0, is_active = 1, last_error_at = NULL
                   WHERE provider = ?""",
                (provider,),
            )
        else:
            result = self.db.execute(
                """UPDATE api_keys
                   SET error_count = 0, is_active = 1, last_error_at = NULL"""
            )
        return result.rowcount if hasattr(result, "rowcount") else 0

    def get_active_count(self, provider: Optional[str] = None) -> int:
        """Count active keys for a provider."""
        if provider:
            row = self.db.fetchone(
                "SELECT COUNT(*) as c FROM api_keys WHERE provider = ? AND is_active = 1",
                (provider,),
            )
        else:
            row = self.db.fetchone(
                "SELECT COUNT(*) as c FROM api_keys WHERE is_active = 1"
            )
        return row["c"] if row else 0

    # ──────────────────────────────────────────────────────────────────────────
    # Environment variable fallback
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _get_env_key(provider: str) -> Optional[str]:
        """Get API key from environment variables."""
        env_map = {
            "anthropic": ["ANTHROPIC_API_KEY"],
            "openai": ["OPENAI_API_KEY"],
            "google": ["GOOGLE_API_KEY", "GEMINI_API_KEY"],
        }
        for env_var in env_map.get(provider, []):
            key = os.environ.get(env_var)
            if key:
                return key
        return None

    @staticmethod
    def detect_provider_from_key(key: str) -> Optional[str]:
        """Detect the provider from the key format."""
        if key.startswith("sk-ant-"):
            return "anthropic"
        elif key.startswith("sk-"):
            return "openai"
        elif key.startswith("AIza"):
            return "google"
        return None

    # ──────────────────────────────────────────────────────────────────────────
    # Bulk operations
    # ──────────────────────────────────────────────────────────────────────────

    def import_from_env(self) -> dict[str, bool]:
        """Import API keys from environment variables into the DB.

        Returns provider → success mapping.
        """
        results: dict[str, bool] = {}

        for provider, env_vars in [
            ("anthropic", ["ANTHROPIC_API_KEY"]),
            ("openai", ["OPENAI_API_KEY"]),
            ("google", ["GOOGLE_API_KEY", "GEMINI_API_KEY"]),
        ]:
            for env_var in env_vars:
                key = os.environ.get(env_var)
                if key:
                    # Check if already imported
                    existing = self.db.fetchone(
                        "SELECT id FROM api_keys WHERE key_value = ?", (key,)
                    )
                    if not existing:
                        self.add_key(provider, key, label=f"imported from {env_var}")
                    results[provider] = True
                    break
            else:
                results[provider] = False

        return results

    def export_keys(self, provider: Optional[str] = None) -> dict[str, str]:
        """Export active keys as provider → key mapping.

        Warning: This returns full key values. Use responsibly.
        """
        rows = self.db.fetchall(
            """SELECT provider, key_value FROM api_keys
               WHERE is_active = 1""" + (" AND provider = ?" if provider else ""),
            (provider,) if provider else (),
        )
        return {r["provider"]: r["key_value"] for r in rows}
