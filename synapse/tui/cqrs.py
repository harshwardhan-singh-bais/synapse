"""
CQRS (Command Query Responsibility Segregation) pattern for the Synapse TUI.

Provides:
- Snapshot-based reads for fast, consistent UI rendering
- Command queue for write operations
- Event sourcing for state changes
- Automatic snapshot refresh

This separates read and write concerns, allowing the TUI to read from
a consistent snapshot while writes are processed asynchronously.
"""
from __future__ import annotations

import copy
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

log = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Commands (write operations)
# ──────────────────────────────────────────────────────────────────────────────


class CommandType(str, Enum):
    """Types of commands that can be executed."""
    CREATE_SESSION = "create_session"
    DELETE_SESSION = "delete_session"
    UPDATE_SESSION = "update_session"
    SEND_MESSAGE = "send_message"
    UPDATE_CONFIG = "update_config"
    CUSTOM = "custom"


@dataclass
class Command:
    """A write command to be executed."""
    type: CommandType
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    command_id: str = ""


@dataclass
class CommandResult:
    """Result of executing a command."""
    success: bool
    command: Command
    error: Optional[str] = None
    data: Any = None


# ──────────────────────────────────────────────────────────────────────────────
# Events (state change notifications)
# ──────────────────────────────────────────────────────────────────────────────


class EventType(str, Enum):
    """Types of events that can occur."""
    SESSION_CREATED = "session_created"
    SESSION_DELETED = "session_deleted"
    SESSION_UPDATED = "session_updated"
    MESSAGE_SENT = "message_sent"
    CONFIG_UPDATED = "config_updated"
    SNAPSHOT_REFRESHED = "snapshot_refreshed"
    CUSTOM = "custom"


@dataclass
class Event:
    """An event representing a state change."""
    type: EventType
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    event_id: str = ""


# ──────────────────────────────────────────────────────────────────────────────
# Snapshot (read model)
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class Snapshot:
    """A point-in-time snapshot of the application state."""
    data: dict[str, Any] = field(default_factory=dict)
    version: int = 0
    timestamp: float = field(default_factory=time.time)

    def get(self, key: str, default: Any = None) -> Any:
        """Get a value from the snapshot."""
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set a value in the snapshot."""
        self.data[key] = value

    def to_dict(self) -> dict[str, Any]:
        """Convert snapshot to a dictionary."""
        return {
            "data": copy.deepcopy(self.data),
            "version": self.version,
            "timestamp": self.timestamp,
        }

    def clone(self) -> Snapshot:
        """Create a deep copy of the snapshot."""
        return Snapshot(
            data=copy.deepcopy(self.data),
            version=self.version,
            timestamp=self.timestamp,
        )


# ──────────────────────────────────────────────────────────────────────────────
# Command handlers
# ──────────────────────────────────────────────────────────────────────────────


class CommandHandler:
    """Handles execution of commands and produces events."""

    def __init__(self) -> None:
        self._handlers: dict[CommandType, Callable[[Command], CommandResult]] = {}

    def register(
        self,
        command_type: CommandType,
        handler: Callable[[Command], CommandResult],
    ) -> None:
        """Register a handler for a command type."""
        self._handlers[command_type] = handler

    def execute(self, command: Command) -> CommandResult:
        """Execute a command and return the result."""
        handler = self._handlers.get(command.type)
        if not handler:
            return CommandResult(
                success=False,
                command=command,
                error=f"No handler registered for command type: {command.type}",
            )

        try:
            return handler(command)
        except Exception as exc:
            return CommandResult(
                success=False,
                command=command,
                error=str(exc),
            )


# ──────────────────────────────────────────────────────────────────────────────
# Event store
# ──────────────────────────────────────────────────────────────────────────────


class EventStore:
    """Stores events and manages subscriptions."""

    def __init__(self, max_events: int = 1000) -> None:
        self._events: deque[Event] = deque(maxlen=max_events)
        self._subscribers: list[Callable[[Event], None]] = []
        self._lock = threading.Lock()

    def append(self, event: Event) -> None:
        """Append an event to the store."""
        with self._lock:
            self._events.append(event)

        # Notify subscribers
        self._notify(event)

    def get_events(
        self,
        event_type: Optional[EventType] = None,
        since: Optional[float] = None,
        limit: int = 100,
    ) -> list[Event]:
        """Get events, optionally filtered by type and time."""
        with self._lock:
            events = list(self._events)

        if event_type:
            events = [e for e in events if e.type == event_type]

        if since:
            events = [e for e in events if e.timestamp > since]

        return events[-limit:]

    def subscribe(self, callback: Callable[[Event], None]) -> None:
        """Subscribe to events."""
        self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[Event], None]) -> None:
        """Unsubscribe from events."""
        try:
            self._subscribers.remove(callback)
        except ValueError:
            pass

    def _notify(self, event: Event) -> None:
        """Notify all subscribers of an event."""
        for callback in self._subscribers:
            try:
                callback(event)
            except Exception as exc:
                log.error("Event subscriber error: %s", exc)


# ──────────────────────────────────────────────────────────────────────────────
# CQRS Manager
# ──────────────────────────────────────────────────────────────────────────────


class CQRSManager:
    """
    CQRS Manager for the Synapse TUI.

    Coordinates:
    - Command execution (write side)
    - Snapshot reads (read side)
    - Event sourcing
    - Automatic snapshot refresh
    """

    def __init__(
        self,
        refresh_interval: float = 1.0,
        max_events: int = 1000,
    ) -> None:
        self.command_handler = CommandHandler()
        self.event_store = EventStore(max_events=max_events)
        self._snapshot = Snapshot()
        self._snapshot_lock = threading.Lock()
        self._refresh_interval = refresh_interval
        self._refresh_thread: Optional[threading.Thread] = None
        self._running = False
        self._version = 0
        self._snapshot_callbacks: list[Callable[[Snapshot], None]] = []

    @property
    def snapshot(self) -> Snapshot:
        """Get the current snapshot (thread-safe)."""
        with self._snapshot_lock:
            return self._snapshot.clone()

    def register_command_handler(
        self,
        command_type: CommandType,
        handler: Callable[[Command], CommandResult],
    ) -> None:
        """Register a command handler."""
        self.command_handler.register(command_type, handler)

    def execute_command(self, command: Command) -> CommandResult:
        """Execute a command and update the snapshot."""
        result = self.command_handler.execute(command)

        if result.success:
            # Update snapshot based on the result
            self._update_snapshot(command, result)

            # Create and store an event
            event = self._create_event(command, result)
            self.event_store.append(event)

        return result

    def _update_snapshot(self, command: Command, result: CommandResult) -> None:
        """Update the snapshot based on a command result."""
        with self._snapshot_lock:
            self._version += 1
            self._snapshot.version = self._version
            self._snapshot.timestamp = time.time()

            # Store command result data in snapshot
            if result.data is not None:
                key = f"{command.type.value}_result"
                self._snapshot.set(key, result.data)

            # Store the command payload for reference
            self._snapshot.set("last_command", {
                "type": command.type.value,
                "timestamp": command.timestamp,
            })

        # Notify snapshot subscribers
        self._notify_snapshot()

    def _create_event(self, command: Command, result: CommandResult) -> Event:
        """Create an event from a command result."""
        event_type_map = {
            CommandType.CREATE_SESSION: EventType.SESSION_CREATED,
            CommandType.DELETE_SESSION: EventType.SESSION_DELETED,
            CommandType.UPDATE_SESSION: EventType.SESSION_UPDATED,
            CommandType.SEND_MESSAGE: EventType.MESSAGE_SENT,
            CommandType.UPDATE_CONFIG: EventType.CONFIG_UPDATED,
            CommandType.CUSTOM: EventType.CUSTOM,
        }

        event_type = event_type_map.get(command.type, EventType.CUSTOM)

        return Event(
            type=event_type,
            payload={
                "command_type": command.type.value,
                "command_payload": command.payload,
                "result_data": result.data,
            },
            timestamp=time.time(),
        )

    def on_snapshot(self, callback: Callable[[Snapshot], None]) -> None:
        """Register a callback for snapshot updates."""
        self._snapshot_callbacks.append(callback)

    def _notify_snapshot(self) -> None:
        """Notify all snapshot subscribers."""
        snapshot = self.snapshot
        for callback in self._snapshot_callbacks:
            try:
                callback(snapshot)
            except Exception as exc:
                log.error("Snapshot callback error: %s", exc)

    # ──────────────────────────────────────────────────────────────────────────
    # Auto-refresh
    # ──────────────────────────────────────────────────────────────────────────

    def start_auto_refresh(self) -> None:
        """Start automatic snapshot refresh."""
        if self._running:
            return

        self._running = True
        self._refresh_thread = threading.Thread(
            target=self._refresh_loop,
            daemon=True,
            name="cqrs-refresh",
        )
        self._refresh_thread.start()

    def stop_auto_refresh(self) -> None:
        """Stop automatic snapshot refresh."""
        self._running = False
        if self._refresh_thread:
            self._refresh_thread.join(timeout=5.0)
            self._refresh_thread = None

    def _refresh_loop(self) -> None:
        """Background loop for automatic snapshot refresh."""
        while self._running:
            time.sleep(self._refresh_interval)
            self._refresh_snapshot()

    def _refresh_snapshot(self) -> None:
        """Refresh the snapshot with current data."""
        with self._snapshot_lock:
            self._snapshot.timestamp = time.time()

        # Emit a snapshot refreshed event
        event = Event(
            type=EventType.SNAPSHOT_REFRESHED,
            payload={"version": self._version},
        )
        self.event_store.append(event)

        # Notify snapshot subscribers
        self._notify_snapshot()

    def refresh_now(self) -> Snapshot:
        """Immediately refresh and return the snapshot."""
        self._refresh_snapshot()
        return self.snapshot

    # ──────────────────────────────────────────────────────────────────────────
    # Query helpers (read side)
    # ──────────────────────────────────────────────────────────────────────────

    def query(self, key: str, default: Any = None) -> Any:
        """Query a value from the current snapshot."""
        return self.snapshot.get(key, default)

    def query_many(self, keys: list[str]) -> dict[str, Any]:
        """Query multiple values from the current snapshot."""
        snap = self.snapshot
        return {key: snap.get(key) for key in keys}

    def get_events(
        self,
        event_type: Optional[EventType] = None,
        since: Optional[float] = None,
        limit: int = 100,
    ) -> list[Event]:
        """Get events from the event store."""
        return self.event_store.get_events(event_type, since, limit)
