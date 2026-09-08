"""
ASCII art & animation helpers for the Synapse TUI.

Provides the blocky SYN▪APSE logo banner, a family of ASCII / Unicode
spinners, progress bars built from block glyphs, and small decorating
utilities used across the interface.
"""

from __future__ import annotations

from rich.text import Text

from . import theme

# ═════════════════════════════════════════════════════════════════════════════
# ASCII logo — "SYNAPSE" in a blocky 7-segment font (5 rows × 55 cols)
# ═════════════════════════════════════════════════════════════════════════════

_S = (" ███████", "██      ", "███████ ", "     ██ ", "███████ ")
_Y = ("██    ██", "██ ██ ██", "████████", "██ ██ ██", "██    ██")
_N = ("███    ██", "████   ██", "██ ██  ██", "██  ██ ██", "██   ████")
_A = (" █████ ", "██   ██", "███████", "██   ██", "██   ██")
_P = ("██████ ", "██   ██", "██████ ", "██     ", "██     ")
_E = ("███████", "██     ", "█████  ", "██     ", "███████")

SYNAPSE_LOGO_LINES: tuple[str, ...] = tuple(
    " ".join(letter) for letter in zip(_S, _Y, _N, _A, _P, _S, _E)
)

# ═════════════════════════════════════════════════════════════════════════════
# Spinners
# ═════════════════════════════════════════════════════════════════════════════

SPINNERS: dict[str, str] = {
    "braille":  "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏",
    "line":     "|/—\\",
    "blocks":   "▁▃▄▅▆▇█▇▆▅▄▃▁",
    "bounce":   "◜◝◞◟",
    "quarters": "◴◷◶◵",
    "pulse":    "▓▒░▒",
    "orbit":    "◐◓◑◒",
    "snake":    "▰▱▰▱",
}


def spinner(kind: str = "braille", tick: int = 0) -> str:
    """Return the spinner glyph for *kind* at frame *tick*."""
    seq = SPINNERS.get(kind, SPINNERS["braille"])
    return seq[tick % len(seq)]


def load_dots(tick: int, count: int = 3) -> str:
    """Three bouncing dots, e.g. ``. → .. → ... → ..``."""
    return "." * (tick % (count * 2) + 1) if tick % (count * 2) < count else "." * ((count * 2) - (tick % (count * 2)))


# ═════════════════════════════════════════════════════════════════════════════
# Progress bars
# ═════════════════════════════════════════════════════════════════════════════


def ascii_bar_text(
    pct: float,
    width: int = 22,
    fill: str = "█",
    empty: str = "░",
    fg: str = theme.GREEN,
) -> Text:
    """A colored ASCII progress bar (filled blocks on dim blocks)."""
    pct = max(0.0, min(100.0, pct))
    filled = round(pct / 100.0 * width)
    body = fill * filled + empty * (width - filled)
    return Text(
        f"[{body}] {filled * 100 // width}%",
        style=f"bold {fg}",
    )


def wave_bar(width: int = 22, tick: int = 0) -> Text:
    """An animated sweeping bar: a bright block glides across a dim rail."""
    rail = "─" * width
    out = Text()
    pos = tick % (width * 2 - 2)
    if pos >= width:
        pos = (width - 1) - (pos - width + 1)
    for idx, ch in enumerate(rail):
        if idx == pos:
            out.append("█", style=f"bold {theme.ACCENT_HI}")
        elif idx in (pos - 1, pos + 1) and 0 <= idx < width:
            out.append("▓", style=theme.ACCENT)
        else:
            out.append("─", style=f"dim {theme.TEXT_FAINT}")
    return out


def rainbow_bar(pct: float, width: int = 22) -> Text:
    """A progress bar whose filled region uses a rainbow gradient."""
    pct = max(0.0, min(100.0, pct))
    filled = round(pct / 100.0 * width)
    out = Text()
    stops = theme.GRADIENT_LOGO
    for idx in range(width):
        if idx >= filled:
            out.append("░", style=f"dim {theme.TEXT_FAINT}")
        else:
            color = stops[int(idx / max(width - 1, 1) * (len(stops) - 1))]
            out.append("█", style=f"bold {color}")
    out.append(f" {int(pct)}%", style=f"bold {theme.TEXT}")
    return out


# ═════════════════════════════════════════════════════════════════════════════
# Logo rendering
# ═════════════════════════════════════════════════════════════════════════════


def colored_logo(stops: tuple[str, ...] = theme.GRADIENT_LOGO) -> list[Text]:
    """Render the SYN▪APSE banner; each letter gets a colour from *stops*."""
    rows: list[Text] = []
    for line in SYNAPSE_LOGO_LINES:
        row = Text()
        for idx, ch in enumerate(line):
            letter_idx = idx // 8  # 7 glyph cols + 1 space
            if ch == " ":
                row.append(" ")
            else:
                row.append(ch, style=f"bold {stops[letter_idx % len(stops)]}")
        rows.append(row)
    return rows


def _wordmark_gradient() -> Text:
    """The single-line rainbow SYN▪APSE wordmark used in the header."""
    import rich.text as _text

    t = _text.Text()
    for idx, ch in enumerate("SYNAPSE"):
        t.append(ch, style=f"bold {theme.GRADIENT_LOGO[idx % len(theme.GRADIENT_LOGO)]}")
    return t


def gradient_rule(width: int = 40, glyph: str = "━") -> str:
    """A horizontal gradient rule (used for separators under titles)."""
    stops = theme.GRADIENT_LOGO
    parts: list[str] = []
    for idx in range(width):
        color = stops[int(idx / max(width - 1, 1) * (len(stops) - 1))]
        parts.append(f"[{color}]{glyph}[/]")
    return "".join(parts)


def brand_line(width: int = 12) -> str:
    """A compact two-tone brand mark, e.g. ``❰❮ SYN▪APSE ❯❱``."""
    return "[#d97757]❰[/][#e89173]❮[/] [#e8e4dc]SYNAPSE[/] [#e89173]❯[/][#d97757]❱[/]"