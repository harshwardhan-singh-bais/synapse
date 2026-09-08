"""
Relay panel — cross-device MQTT relay status and controls.

Shows enabled/disabled state, relay id, broker URL, and recent relay
messages. Action bar: enable / disable / refresh.
"""

from __future__ import annotations

import json
import time

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.widgets import Button, Label, Static

from .. import theme


def _ts_str(ms: int | None) -> str:
    if not ms:
        return "—"
    return time.strftime("%H:%M:%S", time.localtime(ms // 1000))


class RelayPanel(Static):
    """Relay configuration + live status."""

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("  ⇄ RELAY", id="relay-title", classes="dashboard-title")
            with ScrollableContainer(id="relay-scroll"):
                yield Static(id="relay-content")
            with Horizontal(id="relay-actions"):
                yield Button("⏻ Enable", id="relay-on-btn", variant="success")
                yield Button("⏻ Disable", id="relay-off-btn")
                yield Button("⟳ Refresh", id="relay-refresh-btn")

    def on_mount(self) -> None:
        self.refresh_relay()
        self.set_interval(5.0, self.refresh_relay)

    def refresh_relay(self) -> None:
        if not self.visible:
            return
        try:
            db = self.app.db  # type: ignore[attr-defined]
            from ...relay.mqtt_relay import RelayConfig

            relay = RelayConfig(db)
            content = self.query_one("#relay-content", Static)

            enabled = relay.enabled
            relay_id = relay.relay_id
            url = relay.url or "(not configured)"
            token = relay.token

            text = Text()
            # ── Status card ────────────────────────────────────────────────
            text.append("  ┌", style=f"bold {theme.CYAN if enabled else theme.TEXT_FAINT}")
            text.append("─" * 52, style=f"dim {theme.TEXT_FAINT}")
            text.append("┐\n", style=f"bold {theme.CYAN if enabled else theme.TEXT_FAINT}")
            state = "● CONNECTED" if enabled else "○ DISABLED"
            state_color = theme.GREEN if enabled else theme.TEXT_FAINT
            text.append(f"  │  {state:<50} │\n", style=f"bold {state_color}")
            text.append("  └", style=f"bold {theme.CYAN if enabled else theme.TEXT_FAINT}")
            text.append("─" * 52, style=f"dim {theme.TEXT_FAINT}")
            text.append("┘\n\n", style=f"bold {theme.CYAN if enabled else theme.TEXT_FAINT}")

            text.append("  relay id   ", style=f"bold {theme.TEXT_DIM}")
            text.append(f"{relay_id}\n", style=f"bold {theme.CYAN}")
            text.append("  broker url ", style=f"bold {theme.TEXT_DIM}")
            text.append(f"{url}\n", style=f"dim {theme.TEXT_DIM}")
            text.append("  token      ", style=f"bold {theme.TEXT_DIM}")
            if token:
                text.append(f"{token[:24]}…", style=f"dim {theme.TEXT_DIM}")
            else:
                text.append("(none)", style=f"dim {theme.TEXT_FAINT}")
            text.append("\n\n")

            # ── Recent relay activity ──────────────────────────────────────
            text.append("  RECENT RELAY MESSAGES\n", style=f"bold {theme.ACCENT_HI}")
            text.append("  " + "─" * 52 + "\n", style=f"dim {theme.TEXT_FAINT}")
            rows = db.fetchall(
                "SELECT * FROM messages WHERE kind='relay' OR body LIKE '⇄%' ORDER BY created_at DESC LIMIT 8"
            )
            if not rows:
                rows = db.fetchall(
                    "SELECT * FROM messages WHERE from_session_id='relay' ORDER BY created_at DESC LIMIT 8"
                )
            if rows:
                for r in rows:
                    text.append(f"  [{_ts_str(r['created_at'])}]", style=f"dim {theme.TEXT_FAINT}")
                    text.append(f"  {(r.get('body') or '')[:60]}\n", style=f"dim {theme.TEXT_DIM}")
            else:
                text.append("  No relay traffic yet.\n", style="dim italic")

            text.append("\n")
            text.append("  [dim]provision a channel with[/dim] [bold #e89173]synapse relay new --url mqtt://host:1883[/]\n")
            text.append("  [dim]or join one with[/dim] [bold #e89173]synapse relay connect <token> --url mqtt://host:1883[/]\n")

            content.update(text)
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        try:
            db = self.app.db  # type: ignore[attr-defined]
            from ...relay.mqtt_relay import RelayConfig

            relay = RelayConfig(db)
            if btn_id == "relay-on-btn":
                if not relay.url:
                    self.app.notify(  # type: ignore[attr-defined]
                        "No relay URL configured — use `synapse relay new/connect` first.",
                        severity="warning",
                        timeout=5,
                    )
                    return
                relay.enable()
                self.app.notify("Relay enabled.", severity="information", timeout=2)  # type: ignore[attr-defined]
            elif btn_id == "relay-off-btn":
                relay.disable()
                self.app.notify("Relay disabled.", severity="warning", timeout=2)  # type: ignore[attr-defined]
            self.refresh_relay()
        except Exception as exc:
            self.app.notify(str(exc), severity="error", timeout=4)  # type: ignore[attr-defined]


def _json_preview(raw: str | None) -> str:
    if not raw:
        return ""
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data.get("body") or data.get("text") or str(data)[:60]
        return str(data)[:60]
    except Exception:
        return raw[:60]