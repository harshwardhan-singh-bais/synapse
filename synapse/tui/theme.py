"""
Synapse TUI theme — Claude Code premium palette.

Warm charcoal surfaces, a terracotta brand accent (Claude-style), and a
vibrant neon rainbow for statuses, glyphs, bars and highlights.
"""

from __future__ import annotations

from typing import Sequence

from rich.text import Text

# ── Base surfaces ────────────────────────────────────────────────────────────
BG          = "#0e0c12"   # app background (warm near-black, violet tint)
BG_SOFT     = "#111018"   # plain panel
BG_PANEL    = "#15131c"   # raised panel / title bars
BG_PANEL_2  = "#1c1825"   # hover / selected row
BG_INPUT    = "#09080d"   # input wells
BG_FEED     = "#100e16"   # terminal / feed background

EDGE        = "#262230"   # default borders
EDGE_BRIGHT = "#3b3350"   # hover / focus borders

# ── Text ─────────────────────────────────────────────────────────────────────
TEXT        = "#efe9e0"   # warm off-white
TEXT_DIM    = "#968ba2"   # secondary text
TEXT_FAINT  = "#5f566c"   # faint / hints

# ── Claude brand accent ──────────────────────────────────────────────────────
ACCENT      = "#d97757"   # claude terracotta
ACCENT_HI   = "#ff8a5c"   # bright coral
ACCENT_DEEP = "#9c4a32"
ON_ACCENT   = "#1c0f07"

# ── Vibrant neon palette ─────────────────────────────────────────────────────
RED     = "#ff5d6b"
ORANGE  = "#ff9f43"
YELLOW  = "#ffd166"
GREEN   = "#3ddc97"
TEAL    = "#2be0c8"
CYAN    = "#5fd4ff"
BLUE    = "#6ea8ff"
PURPLE  = "#c792ea"
PINK    = "#ff5d8f"

# Rainbow used for gradient text / logos
GRADIENT_LOGO = (ACCENT_HI, ORANGE, YELLOW, GREEN, TEAL, CYAN, BLUE, PURPLE, PINK)
GRADIENT_RUN  = (GREEN, TEAL, CYAN)
GRADIENT_SESS = (ACCENT_HI, YELLOW, GREEN)

# ── Semantic status colors (fg on bg) ────────────────────────────────────────
STATUS_FG: dict[str, str] = {
    "idle":        TEXT_DIM,
    "active":      GREEN,
    "working":     GREEN,
    "running":     GREEN,
    "blocked":     RED,
    "error":       RED,
    "failed":      RED,
    "done":        CYAN,
    "completed":   CYAN,
    "paused":      YELLOW,
    "pending":     TEXT_FAINT,
    "unreachable": YELLOW,
}

STATUS_BG: dict[str, str] = {
    "idle":        "#18151f",
    "active":      "#0e2a21",
    "working":     "#0e2a21",
    "running":     "#0e2a21",
    "blocked":     "#341820",
    "error":       "#341820",
    "failed":      "#341820",
    "done":        "#0e2433",
    "completed":   "#0e2433",
    "paused":      "#33250c",
    "pending":     "#1a1622",
    "unreachable": "#33250c",
}

# ── Agent chip colors (hash → hue) ───────────────────────────────────────────
AGENT_COLORS = (CYAN, PURPLE, PINK, YELLOW, BLUE, GREEN, ORANGE, TEAL, RED)


def hex_text(text: str, color: str, *, bold: bool = False, dim: bool = False) -> Text:
    """A single-color rich :class:`Text`."""
    style = color
    if bold:
        style = f"bold {style}"
    if dim:
        style = f"dim {style}"
    return Text(text, style=style)


def gradient_text(text: str, stops: Sequence[str] = GRADIENT_LOGO, *, bold: bool = True) -> Text:
    """Build a :class:`Text` where each character is coloured along a gradient.

    The gradient is interpolated across the whole string so it forms a smooth
    rainbow spectrum (perfect for logos and titles).
    """
    out = Text()
    n = len(text)
    spans = len(stops)
    for idx, ch in enumerate(text):
        if ch == " ":
            out.append(" ")
            continue
        if n <= 1:
            pos = 0
        else:
            pos = int(idx / (n - 1) * (spans - 1))
        style = stops[pos]
        if bold:
            style = f"bold {style}"
        out.append(ch, style=style)
    return out


def pill(text: str, fg: str, bg: str, *, bold: bool = True) -> Text:
    """A compact colored 'pill' — used for status badges and chips."""
    style = f"{fg} on {bg}"
    if bold:
        style = f"bold {style}"
    return Text(text, style=style)


def dim(*parts) -> Text:
    """Dim leftover pieces."""
    return Text.assemble(*parts)


def status_pill(status: str) -> Text:
    """Return a colored pill for a session/run status."""
    key = (status or "idle").lower()
    fg = STATUS_FG.get(key, TEXT_DIM)
    bg = STATUS_BG.get(key, "#18151f")
    return pill(f" {key} ", fg, bg)


def agent_color(agent: str) -> str:
    """Stable vibrant color derived from an agent name."""
    if not agent:
        return PURPLE
    return AGENT_COLORS[sum(ord(c) for c in agent) % len(AGENT_COLORS)]