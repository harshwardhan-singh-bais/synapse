"""
ASCII loading widgets & boot experience.

Contains:
- ``AsciiLoading``       — an animated ASCII spinner + label + bouncing dots
- ``ProgressBarLoader``  — a sweeping ASCII progress bar
- ``BootScreen``         — fullscreen ASCII-art boot sequence at launch
- ``LoaderShowcaseScreen`` — a demo screen cycling every spinner style
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import Label, Static

from ..ascii import colored_logo, load_dots, rainbow_bar, spinner, wave_bar
from .. import theme

# ═════════════════════════════════════════════════════════════════════════════
# Animated widgets
# ═════════════════════════════════════════════════════════════════════════════


class AsciiLoading(Static):
    """Animated ``{spinner} message.dots`` line."""

    def __init__(
        self,
        text: str = "loading",
        spinner_kind: str = "braille",
        *,
        color: str = theme.CYAN,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self._text = text
        self._spinner_kind = spinner_kind
        self._color = color
        self._tick = 0

    def on_mount(self) -> None:
        self._tick = 0
        self.update(self._render())
        self.set_interval(0.09, self._advance)

    def set_text(self, text: str) -> None:
        """Swap the message without restarting the widget."""
        self._text = text

    def _advance(self) -> None:
        self._tick += 1
        self.update(self._render())

    def _render(self) -> Text:
        return Text(
            f" {spinner(self._spinner_kind, self._tick)}  {self._text}"
            f"{load_dots(self._tick)}",
            style=f"bold {self._color}",
        )


class ProgressBarLoader(Static):
    """A sweeping rainbow progress bar that loops 0 → 100%."""

    def __init__(self, width: int = 26, *, id: str | None = None, classes: str | None = None) -> None:
        super().__init__(id=id, classes=classes)
        self._width = width
        self._tick = 0

    def on_mount(self) -> None:
        self._tick = 0
        self.set_interval(0.05, self._advance)

    def _advance(self) -> None:
        self._tick += 1
        self.update(self._render())

    def _render(self) -> Text:
        return wave_bar(self._width, self._tick)


# ═════════════════════════════════════════════════════════════════════════════
# Boot screen
# ═════════════════════════════════════════════════════════════════════════════


class BootScreen(ModalScreen[None]):
    """Fullscreen ASCII boot sequence shown when the TUI starts.

    Dismisses itself after ~3 seconds or on any key / click.
    """

    BINDINGS = [
        ("escape", "skip", "Skip boot"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="boot-box"):
            yield Static(id="boot-logo")
            yield Static(id="boot-status")
            yield Static(id="boot-bar")
            yield Label("  press any key to skip", id="boot-hint")
        yield Label("SYN·APSE  v0.1", id="boot-version")

    def on_mount(self) -> None:
        self._tick = 0
        self.set_interval(0.06, self._tick_handler)
        self.set_timer(3.0, self._finish)

    def _tick_handler(self) -> None:
        self._tick += 1
        logo = self.query_one("#boot-logo", Static)
        status = self.query_one("#boot-status", Static)
        bar = self.query_one("#boot-bar", Static)
        logo.update(Text("\n".join(str(l) for l in colored_logo())))
        pct = min(100, int(self._tick / 8 * 100))
        status.update(
            Text(
                f" {spinner('braille', self._tick)}  powering up the mesh"
                f"{load_dots(self._tick)}",
                style=f"bold {theme.TEXT_DIM}",
            )
        )
        bar.update(rainbow_bar(pct, 26))

    def _finish(self) -> None:
        if self.app.screen == self:
            self.dismiss(None)

    def action_skip(self) -> None:
        self.dismiss(None)

    def on_key(self, event) -> None:
        if self.app.screen is self:
            event.prevent_default()
            self.dismiss(None)


# ═════════════════════════════════════════════════════════════════════════════
# Loader showcase (demo of the ASCII loading styles)
# ═════════════════════════════════════════════════════════════════════════════


class LoaderShowcaseScreen(Screen[None]):
    """Displays every built-in ASCII spinner racing, plus a rainbow bar."""

    BINDINGS = [
        ("escape", "close", "Close showcase"),
        ("q", "close", "Close showcase"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="loader-showcase"):
            yield Label("  ⚡ ASCII LOADER SHOWCASE", id="showcase-title")
            yield AsciiLoading("braille · thinking", "braille", id="load-braille")
            yield AsciiLoading("line · linking", "line", id="load-line", color=theme.ACCENT_HI)
            yield AsciiLoading("blocks · rendering", "blocks", id="load-blocks", color=theme.GREEN)
            yield AsciiLoading("bounce · bouncing", "bounce", id="load-bounce", color=theme.PINK)
            yield AsciiLoading("quarters · syncing", "quarters", id="load-quarters", color=theme.YELLOW)
            yield AsciiLoading("pulse · pulsing", "pulse", id="load-pulse", color=theme.PURPLE)
            yield AsciiLoading("orbit · weaving", "orbit", id="load-orbit", color=theme.TEAL)
            yield AsciiLoading("snake · crawling", "snake", id="load-snake", color=theme.BLUE)
            yield Label("", id="showcase-spacer")
            yield ProgressBarLoader(width=30, id="showcase-bar")
            yield Label("\n  press [bold #ff8a5c]q[/] or [bold #ff8a5c]esc[/] to close", id="showcase-hint")

    def action_close(self) -> None:
        self.app.pop_screen()  # type: ignore[attr-defined]