"""
Messenger — send, receive, and manage inter-session messages.
Supports: direct messages, broadcast, thread replies, collision alerts.
Message delivery: polling-based (no background daemon required).
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from ..db.database import Database
from ..session.models import MessageRecord

log = logging.getLogger(__name__)


class Messenger:
    """All inter-session messaging operations backed by the ``messages`` table."""

    def __init__(self, db: Database) -> None:
        self.db = db

    # ──────────────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────────────

    def _row_to_record(self, row: object) -> MessageRecord:
        return MessageRecord.model_validate(dict(row))  # type: ignore[call-overload, arg-type]

    def _now_ms(self) -> int:
        return self.db.now_ms()

    # ──────────────────────────────────────────────────────────────
    # Core send / receive
    # ──────────────────────────────────────────────────────────────

    def resolve_mentions(self, body: str, from_session_id: Optional[str] = None) -> list[str]:
        """Extract @mention targets from message body and resolve to session IDs.

        Looks for patterns like ``@session-name`` or ``@<session-uuid-prefix>``
        in the message body. Returns a list of resolved session IDs.

        Also supports ``@all`` for broadcast targeting.
        """
        import re
        mentions = re.findall(r"@([\w-]+)", body)
        if not mentions:
            return []

        resolved: list[str] = []
        for mention in mentions:
            if mention.lower() == "all":
                return ["__broadcast__"]  # Special sentinel for broadcast

            # Try to resolve as session name or ID prefix
            row = self.db.fetchone(
                "SELECT id FROM sessions WHERE name = ? AND deleted_at IS NULL",
                (mention,),
            )
            if row:
                resolved.append(row["id"])
                continue

            # Try as ID prefix
            rows = self.db.fetchall(
                "SELECT id FROM sessions WHERE id LIKE ? AND deleted_at IS NULL",
                (f"{mention}%",),
            )
            if len(rows) == 1:
                resolved.append(rows[0]["id"])

        return resolved

    def send(
        self,
        body: str,
        to_session_id: Optional[str] = None,   # None = broadcast
        from_session_id: Optional[str] = None,
        kind: str = "chat",
        thread_id: Optional[str] = None,
        intent: str = "inform",
    ) -> MessageRecord:
        """Insert a message row and return the created :class:`MessageRecord`."""
        now = self._now_ms()
        conn = self.db.connect()
        cur = conn.execute(
            """
            INSERT INTO messages
                (to_session_id, from_session_id, kind, body, thread_id, intent, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (to_session_id, from_session_id, kind, body, thread_id, intent, now),
        )
        row = self.db.fetchone(
            "SELECT * FROM messages WHERE id = ?", (cur.lastrowid,)
        )
        assert row is not None, "Insert succeeded but row not found"
        log.debug(
            "Message sent id=%d kind=%s to=%s from=%s",
            row["id"], kind, to_session_id, from_session_id,
        )
        return self._row_to_record(row)

    def inbox(self, session_id: str, limit: int = 50) -> list[MessageRecord]:
        """Return unclaimed messages addressed to *session_id* or broadcast (``to_session_id IS NULL``)."""
        rows = self.db.fetchall(
            """
            SELECT * FROM messages
            WHERE (to_session_id = ? OR to_session_id IS NULL)
              AND claimed_at IS NULL
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (session_id, limit),
        )
        return [self._row_to_record(r) for r in rows]

    def claim(self, session_id: str, limit: int = 10) -> list[MessageRecord]:
        """Atomic exactly-once drain: stamp ``claimed_at`` and return the rows.

        Only messages addressed directly to *session_id* (not broadcasts) are
        claimed, to avoid one agent stealing messages destined for others.
        """
        now = self._now_ms()
        conn = self.db.connect()

        # Identify the IDs to claim in a single atomic operation.
        conn.execute("BEGIN IMMEDIATE")
        try:
            id_rows = conn.execute(
                """
                SELECT id FROM messages
                WHERE to_session_id = ?
                  AND claimed_at IS NULL
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()

            if not id_rows:
                conn.execute("COMMIT")
                return []

            ids = [r[0] for r in id_rows]
            placeholders = ",".join("?" * len(ids))
            conn.execute(
                f"UPDATE messages SET claimed_at = ? WHERE id IN ({placeholders})",
                [now, *ids],
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

        rows = self.db.fetchall(
            f"SELECT * FROM messages WHERE id IN ({placeholders})", ids
        )
        log.debug("Claimed %d messages for session %s", len(rows), session_id)
        return [self._row_to_record(r) for r in rows]

    def reply(
        self,
        original_message_id: int,
        body: str,
        from_session_id: Optional[str] = None,
    ) -> MessageRecord:
        """Reply in the same thread as *original_message_id*.

        The reply is addressed to the *sender* of the original message
        (``from_session_id`` → ``to_session_id``).
        """
        original = self.db.fetchone(
            "SELECT * FROM messages WHERE id = ?", (original_message_id,)
        )
        if original is None:
            raise ValueError(f"Message {original_message_id} not found")

        thread_id = original["thread_id"] or str(original_message_id)
        to_session_id = original["from_session_id"]

        return self.send(
            body=body,
            to_session_id=to_session_id,
            from_session_id=from_session_id,
            kind=original["kind"] or "chat",
            thread_id=thread_id,
            intent="ack",
        )

    # ──────────────────────────────────────────────────────────────
    # Subscriptions
    # ──────────────────────────────────────────────────────────────

    def subscribe(
        self,
        session_id: str,
        filter_type: str,
        filter_spec: dict[str, object],
    ) -> int:
        """Register a subscription rule; returns the new subscription ID."""
        now = self._now_ms()
        cur = self.db.execute(
            """
            INSERT INTO subscriptions (session_id, filter_type, filter_spec, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (session_id, filter_type, json.dumps(filter_spec), now),
        )
        sub_id: int = cur.lastrowid or 0
        log.debug("Subscription %d created for session %s type=%s", sub_id, session_id, filter_type)
        return sub_id

    def unsubscribe(self, subscription_id: int) -> bool:
        """Delete a subscription by ID. Returns ``True`` if a row was deleted."""
        cur = self.db.execute(
            "DELETE FROM subscriptions WHERE id = ?", (subscription_id,)
        )
        deleted = cur.rowcount > 0
        if deleted:
            log.debug("Subscription %d removed", subscription_id)
        else:
            log.warning("Subscription %d not found", subscription_id)
        return deleted

    def list_subscriptions(self, session_id: str) -> list[dict[str, object]]:
        """Return all subscriptions for *session_id* as plain dicts."""
        rows = self.db.fetchall(
            "SELECT * FROM subscriptions WHERE session_id = ? ORDER BY created_at ASC",
            (session_id,),
        )
        result: list[dict[str, object]] = []
        for row in rows:
            entry = dict(row)
            try:
                entry["filter_spec"] = json.loads(entry["filter_spec"] or "{}")
            except (json.JSONDecodeError, TypeError):
                entry["filter_spec"] = {}
            result.append(entry)
        return result

    # ──────────────────────────────────────────────────────────────
    # Collision detection
    # ──────────────────────────────────────────────────────────────

    def alert_collision(self, session_a: str, session_b: str, file_path: str) -> None:
        """Emit a collision alert to both sessions."""
        body = (
            f"⚠️ COLLISION: Both sessions edited {file_path} within 30s of each other. "
            "Coordinate before continuing."
        )
        self.send(body=body, to_session_id=session_a, kind="collision", intent="inform")
        self.send(body=body, to_session_id=session_b, kind="collision", intent="inform")
        log.warning("Collision alert sent: %s <-> %s on %s", session_a, session_b, file_path)

    def send_with_mentions(
        self,
        body: str,
        from_session_id: Optional[str] = None,
        kind: str = "chat",
        intent: str = "inform",
    ) -> list[MessageRecord]:
        """Send a message, resolving @mentions to target sessions.

        If ``@all`` is found, broadcasts to all sessions.
        If specific ``@name`` mentions are found, sends to each mentioned session.
        If no mentions are found, broadcasts to all.
        Returns a list of all messages sent.
        """
        mentions = self.resolve_mentions(body, from_session_id)
        sent: list[MessageRecord] = []

        if not mentions or mentions == ["__broadcast__"]:
            # Broadcast to all
            msg = self.send(
                body=body,
                to_session_id=None,
                from_session_id=from_session_id,
                kind=kind,
                intent=intent,
            )
            sent.append(msg)
        else:
            # Send to each mentioned session
            for session_id in mentions:
                msg = self.send(
                    body=body,
                    to_session_id=session_id,
                    from_session_id=from_session_id,
                    kind=kind,
                    intent=intent,
                )
                sent.append(msg)

        return sent

    def check_collisions(self, window_secs: int = 30) -> list[tuple[str, str, str]]:
        """Detect file-edit collisions within the last *window_secs* seconds.

        Queries the ``events`` table for ``file_edit`` events, groups them by
        ``file_path`` (stored in the JSON ``data`` payload), and returns
        ``(session_a, session_b, file_path)`` tuples where two different
        sessions edited the same file within the window.
        """
        cutoff_ms = self._now_ms() - (window_secs * 1_000)
        rows = self.db.fetchall(
            """
            SELECT session_id, data, timestamp
            FROM events
            WHERE type = 'file_edit'
              AND timestamp >= ?
            ORDER BY timestamp ASC
            """,
            (cutoff_ms,),
        )

        # file_path → list of (session_id, timestamp)
        file_edits: dict[str, list[tuple[str, int]]] = {}
        for row in rows:
            try:
                payload = json.loads(row["data"] or "{}")
                file_path: str = payload.get("file_path", "")
            except (json.JSONDecodeError, TypeError):
                continue
            if not file_path:
                continue
            file_edits.setdefault(file_path, []).append(
                (row["session_id"], row["timestamp"])
            )

        collisions: list[tuple[str, str, str]] = []
        for file_path, edits in file_edits.items():
            # Find pairs of different sessions that edited within window_secs.
            seen: dict[str, int] = {}  # session_id → latest timestamp
            for session_id, ts in edits:
                for other_session, other_ts in seen.items():
                    if other_session != session_id and abs(ts - other_ts) <= window_secs * 1_000:
                        pair = (
                            min(session_id, other_session),
                            max(session_id, other_session),
                            file_path,
                        )
                        if pair not in collisions:
                            collisions.append(pair)
                seen[session_id] = ts

        return collisions
