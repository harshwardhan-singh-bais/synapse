"""
Collision detector — watches the events table for file_edit events
and raises alerts when two sessions edit the same file within 30 seconds.
"""
from __future__ import annotations

import threading
import time
from typing import Optional

from ..db.database import Database
from ..messaging.messenger import Messenger


class CollisionDetector:
    """
    Background thread that polls the ``events`` table every 10 seconds.

    Detects when two sessions edit the same file within *window_secs* seconds
    (default: 30 s). Emits collision alerts to both sessions via
    :class:`~synapse.messaging.messenger.Messenger`.

    Already-alerted pairs are debounced for 5 minutes to avoid alert storms.
    """

    def __init__(
        self,
        db: Database,
        messenger: Messenger,
        window_secs: int = 30,
        poll_interval: int = 10,
    ) -> None:
        self.db = db
        self.messenger = messenger
        self.window_secs = window_secs
        self.poll_interval = poll_interval
        self._thread: Optional[threading.Thread] = None
        self._running = False
        # Set of (session_a, session_b, file_path) tuples already alerted this window.
        self._seen_collisions: set[tuple[str, str, str]] = set()

    # ──────────────────────────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the detector background thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="synapse-collision-detector"
        )
        self._thread.start()

    def stop(self) -> None:
        """Signal the background thread to stop after its current sleep."""
        self._running = False

    # ──────────────────────────────────────────────────────────────
    # Internal
    # ──────────────────────────────────────────────────────────────

    def _run(self) -> None:
        while self._running:
            try:
                self._check()
            except Exception:
                pass  # Errors in detection are non-fatal — keep polling
            time.sleep(self.poll_interval)

    def _check(self) -> None:
        collisions = self.messenger.check_collisions(self.window_secs)
        for session_a, session_b, file_path in collisions:
            # Normalise pair ordering so (a,b,f) == (b,a,f).
            key: tuple[str, str, str] = (
                min(session_a, session_b),
                max(session_a, session_b),
                file_path,
            )
            if key not in self._seen_collisions:
                self._seen_collisions.add(key)
                try:
                    self.messenger.alert_collision(session_a, session_b, file_path)
                except Exception:
                    pass
                # Re-allow alerting the same pair after 5 minutes.
                threading.Timer(
                    300.0,
                    lambda k=key: self._seen_collisions.discard(k),
                ).start()
