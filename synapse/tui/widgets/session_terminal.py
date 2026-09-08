"""
Session terminal — live tmux capture from the session's pane.
Falls back to DB event feed when tmux capture is unavailable.
"""
from __future__ import annotations

import subprocess
import time
from typing import Optional

from textual.app import ComposeResult
from textual.containers import ScrollableContainer
from textual.reactive import reactive
from textual.widgets import Log, Static
from rich.text import Text

from .. import theme


_PLACEHOLDER = (
    "  [bold #e89173]❯[/] [bold #e8e4dc]no session selected[/]\n\n"
    "  [dim #a8a196]select a session from the sidebar to peer into its terminal.[/]\n"
    "  [dim #a8a196]press [/][bold #e89173]n[/][dim] to mint a new session.[/]"
)

_NO_OUTPUT = "  [dim #6e685d]no terminal output captured yet for this session.[/]"

TMUX_SOCKET = "synapse"


def _capture_pane(pane_id: str, lines: int = 200) -> Optional[str]:
    """Capture terminal output from a tmux pane via capture-pane -p."""
    try:
        result = subprocess.run(
            ["tmux", "-L", TMUX_SOCKET, "capture-pane", "-p", "-t", pane_id, "-S", f"-{lines}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


class SessionTerminal(Static):
    """
    Shows live tmux capture from the selected session's pane.
    Refreshes every 1.5 seconds when an active session is selected.
    Falls back to DB event feed if tmux capture is unavailable.
    """

    session_id: reactive[Optional[str]] = reactive(None)
    backend_id: reactive[Optional[str]] = reactive(None)

    def compose(self) -> ComposeResult:
        with ScrollableContainer(id="terminal-scroll"):
            yield Log(id="terminal-log", highlight=True)

    def on_mount(self) -> None:
        self.set_interval(1.5, self.refresh_content)
        log = self.query_one("#terminal-log", Log)
        log.write(_PLACEHOLDER)

    def watch_session_id(self, session_id: Optional[str]) -> None:
        """Called whenever the selected session changes."""
        log = self.query_one("#terminal-log", Log)
        log.clear()
        self.backend_id = None

        if session_id is None:
            log.write(_PLACEHOLDER)
        else:
            log.write(f"  [bold #6ba5c9]…[/] loading terminal output for "
                      f"[bold #d8b04c]{session_id[:8]}[/]…\n")
            # Resolve backend_id from DB
            try:
                db = self.app.db  # type: ignore[attr-defined]
                row = db.fetchone(
                    "SELECT backend_id FROM sessions WHERE id = ?", (session_id,)
                )
                if row and row["backend_id"]:
                    self.backend_id = row["backend_id"]
            except Exception:
                pass
            self.refresh_content()

    def refresh_content(self) -> None:
        """Pull the latest terminal output — tmux capture preferred, DB fallback."""
        if self.session_id is None:
            return

        log_widget = self.query_one("#terminal-log", Log)

        # Try tmux capture first
        if self.backend_id:
            output = _capture_pane(self.backend_id, lines=200)
            if output:
                log_widget.clear()
                # Strip trailing blank lines
                lines = output.rstrip().split("\n")
                log_widget.write("\n".join(lines))
                return

        # Fallback: show session info + DB events
        try:
            db = self.app.db  # type: ignore[attr-defined]

            session_row = db.fetchone(
                "SELECT * FROM sessions WHERE id = ?", (self.session_id,)
            )

            # Get recent events
            event_rows = db.fetchall(
                """
                SELECT data, timestamp, type FROM events
                WHERE session_id = ?
                ORDER BY timestamp DESC
                LIMIT 100
                """,
                (self.session_id,),
            )

            log_widget.clear()

            if session_row:
                s = dict(session_row)
                status = (s.get("status") or "unknown").lower()
                agent = s.get("agent") or "?"
                name = s.get("name") or "?"
                cwd = s.get("cwd") or "?"
                session_id = (s.get("id") or self.session_id or "?")[:8]

                # Status color
                status_style = theme.STATUS_FG.get(status, theme.TEXT)
                status_bg = theme.STATUS_BG.get(status, "#18151f")
                agent_color = theme.agent_color(agent)

                log_widget.write(
                    f"  [bold #e89173]❯[/] [bold #e8e4dc]{name}[/]"
                    f"  [{status_style} on {status_bg}]{status.upper():^10}[/]\n"
                    f"  [dim #a8a196]agent [/][bold {agent_color}]{agent}[/]"
                    f"  [dim #6e685d]·  cwd:[/] [dim #a8a196]{cwd}[/]\n"
                    f"  [dim #a8a196]backend [/][bold #6ba5c9]{self.backend_id or 'none'}[/]"
                    f"  [dim #6e685d]·  id:[/] [bold #a68ec9]{session_id}[/]\n"
                    f"  [dim]{'─' * 54}[/]\n"
                )

            if event_rows:
                import json as _json

                for row in reversed(event_rows[:60]):
                    try:
                        data = _json.loads(row["data"] or "{}")
                        ts = row["timestamp"] // 1000
                        t = time.strftime("%H:%M:%S", time.localtime(ts))
                        ev_type = row["type"]

                        if ev_type == "message":
                            msg = data.get("body", str(data))[:110]
                            log_widget.write(
                                f"  [dim #6e685d][{t}][/] [bold #c983a2]💬[/] "
                                f"[#e8e4dc]{msg}[/]"
                            )
                        elif ev_type == "status":
                            st = data.get("status", str(data))
                            st = (str(st)).lower()
                            st_fg = theme.STATUS_FG.get(st, "#a68ec9")
                            log_widget.write(
                                f"  [dim #6e685d][{t}][/] [bold {st_fg}]◉[/]"
                                f" [{st_fg}]STATE[/] → [bold {st_fg}]{st}[/]"
                            )
                        elif ev_type == "file_edit":
                            fp = data.get("file_path", "?")
                            log_widget.write(
                                f"  [dim #6e685d][{t}][/] [bold #d8b04c]✎[/]"
                                f" [#d8b04c]EDIT[/]    [dim #a8a196]{fp}[/]"
                            )
                        elif ev_type == "tool_call":
                            tool = data.get("tool", "?")
                            log_widget.write(
                                f"  [dim #6e685d][{t}][/] [bold #6ba5c9]⚙[/]"
                                f" [#6ba5c9]TOOL[/]    [bold #6ba5c9]{tool}[/]"
                            )
                        elif ev_type == "collision":
                            msg = data.get("body", str(data))[:110]
                            log_widget.write(
                                f"  [dim #6e685d][{t}][/] [bold #e5534b]⚠[/]"
                                f" [#e5534b]COLLISION[/] {msg}"
                            )
                        else:
                            log_widget.write(
                                f"  [dim #6e685d][{t}][/] [bold #a68ec9]{ev_type}[/]: "
                                f"[dim #a8a196]{str(data)[:80]}[/]"
                            )
                    except Exception:
                        continue
            else:
                log_widget.write(f"  {_NO_OUTPUT}")

        except Exception as exc:
            log_widget.clear()
            log_widget.write(f"  Error loading terminal output:\n  {exc}")
