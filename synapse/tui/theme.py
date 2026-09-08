"""
Synapse TUI theme — professional Claude Code palette.

A restrained, editor-grade surface system: warm graphite backgrounds, one
terracotta brand accent (Claude-style), and muted semantic status colors.
Color is information, not decoration.
"""

from __future__ import annotations

from typing import Sequence

from rich.text import Text

# ── Base surfaces (warm graphite, slightly elevated) ─────────────────────────
BG          = "#1a1917"   # app background
BG_SOFT     = "#201f1c"   # plain panel
BG_PANEL    = "#242220"   # raised panel / title bars
BG_PANEL_2  = "#2c2a27"   # hover / selected row
BG_INPUT    = "#141311"   # input wells
BG_FEED     = "#171614"   # terminal / feed background

EDGE        = "#38352f"   # default borders (hairline)
EDGE_BRIGHT = "#524e45"   # hover / focus borders

# ── Text ─────────────────────────────────────────────────────────────────────
TEXT        = "#e8e4dc"   # warm off-white
TEXT_DIM    = "#a8a196"   # secondary text
TEXT_FAINT  = "#6e685d"   # faint / hints

# ── Claude brand accent ──────────────────────────────────────────────────────
ACCENT      = "#d97757"   # claude terracotta
ACCENT_HI   = "#e89173"   # soft coral (hover)
ACCENT_DEEP = "#b35c3e"
ON_ACCENT   = "#1c0f07"

# ── Semantic accents (muted, functional) ─────────────────────────────────────
RED     = "#e5534b"
ORANGE  = "#d9864a"
YELLOW  = "#d8b04c"
GREEN   = "#69b583"
TEAL    = "#56a8a0"
CYAN    = "#6ba5c9"
BLUE    = "#7a9ec9"
PURPLE  = "#a68ec9"
PINK    = "#c983a2"

# Soft tints used for status pill backgrounds
TINT_GREEN   = "#22352a"
TINT_YELLOW  = "#38311d"
TINT_RED     = "#3a2622"
TINT_CYAN    = "#1f2f38"
TINT_NEUTRAL = "#28251f"

# Muted accent set for agent/category chips
AGENT_COLORS = (CYAN, PURPLE, PINK, YELLOW, BLUE, GREEN, ORANGE, TEAL, RED)

# Legacy gradient constants — now quiet accent ramps used by old call sites.
GRADIENT_LOGO = (ACCENT_HI, ACCENT, ACCENT_DEEP)
GRADIENT_RUN  = (GREEN, TEAL, CYAN)
GRADIENT_SESS = (ACCENT_HI, ACCENT, ACCENT_DEEP)

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
    "idle":        TINT_NEUTRAL,
    "active":      TINT_GREEN,
    "working":     TINT_GREEN,
    "running":     TINT_GREEN,
    "blocked":     TINT_RED,
    "error":       TINT_RED,
    "failed":      TINT_RED,
    "done":        TINT_CYAN,
    "completed":   TINT_CYAN,
    "paused":      TINT_YELLOW,
    "pending":     TINT_NEUTRAL,
    "unreachable": TINT_YELLOW,
}


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
        pos = int(idx / max(n - 1, 1) * (spans - 1))
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
    bg = STATUS_BG.get(key, TINT_NEUTRAL)
    return pill(f" {key} ", fg, bg)


def agent_color(agent: str) -> str:
    """Stable vibrant color derived from an agent name."""
    if not agent:
        return PURPLE
    return AGENT_COLORS[sum(ord(c) for c in agent) % len(AGENT_COLORS)]