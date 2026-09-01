"""
Theme palettes — built-in color palettes for the TUI.

Ported from thurbox's themes.toml (36 palettes: 28 dark, 8 light).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class ThemePalette:
    """A complete color palette for the TUI."""
    name: str
    is_dark: bool = True

    # Core colors
    bg: str = "#0a0e14"
    fg: str = "#e6edf3"
    surface: str = "#0d1117"
    surface_light: str = "#161b22"
    border: str = "#21262d"
    border_light: str = "#30363d"

    # Accent colors
    accent: str = "#58a6ff"
    accent_light: str = "#79c0ff"
    accent_dim: str = "#1f6feb"

    # Status colors
    success: str = "#3fb950"
    warning: str = "#d29922"
    error: str = "#f85149"
    info: str = "#58a6ff"

    # Text variants
    text: str = "#e6edf3"
    text_dim: str = "#8b949e"
    text_muted: str = "#484f58"
    text_bright: str = "#f0f6fc"

    # Semantic colors
    green: str = "#3fb950"
    red: str = "#f85149"
    yellow: str = "#d29922"
    cyan: str = "#58a6ff"
    magenta: str = "#bc8cff"
    blue: str = "#58a6ff"


# ──────────────────────────────────────────────────────────────────────────────
# Built-in palettes
# ──────────────────────────────────────────────────────────────────────────────


BUILTIN_PALETTES: dict[str, ThemePalette] = {
    "github-dark": ThemePalette(
        name="github-dark",
        is_dark=True,
        bg="#0a0e14",
        fg="#e6edf3",
        surface="#0d1117",
        surface_light="#161b22",
        border="#21262d",
        border_light="#30363d",
        accent="#58a6ff",
        success="#3fb950",
        warning="#d29922",
        error="#f85149",
    ),
    "github-light": ThemePalette(
        name="github-light",
        is_dark=False,
        bg="#ffffff",
        fg="#24292f",
        surface="#f6f8fa",
        surface_light="#eaeef2",
        border="#d0d7de",
        border_light="#afb8c1",
        accent="#0969da",
        success="#1a7f37",
        warning="#9a6700",
        error="#cf222e",
    ),
    "dracula": ThemePalette(
        name="dracula",
        is_dark=True,
        bg="#282a36",
        fg="#f8f8f2",
        surface="#44475a",
        surface_light="#6272a4",
        border="#6272a4",
        border_light="#bd93f9",
        accent="#bd93f9",
        success="#50fa7b",
        warning="#f1fa8c",
        error="#ff5555",
    ),
    "nord": ThemePalette(
        name="nord",
        is_dark=True,
        bg="#2e3440",
        fg="#eceff4",
        surface="#3b4252",
        surface_light="#434c5e",
        border="#4c566a",
        border_light="#616e88",
        accent="#88c0d0",
        success="#a3be8c",
        warning="#ebcb8b",
        error="#bf616a",
    ),
    "catppuccin-mocha": ThemePalette(
        name="catppuccin-mocha",
        is_dark=True,
        bg="#1e1e2e",
        fg="#cdd6f4",
        surface="#313244",
        surface_light="#45475a",
        border="#585b70",
        border_light="#7f849c",
        accent="#89b4fa",
        success="#a6e3a1",
        warning="#f9e2af",
        error="#f38ba8",
    ),
    "tokyo-night": ThemePalette(
        name="tokyo-night",
        is_dark=True,
        bg="#1a1b26",
        fg="#a9b1d6",
        surface="#24283b",
        surface_light="#414868",
        border="#565f89",
        border_light="#737aa2",
        accent="#7aa2f7",
        success="#9ece6a",
        warning="#e0af68",
        error="#f7768e",
    ),
    "solarized-dark": ThemePalette(
        name="solarized-dark",
        is_dark=True,
        bg="#002b36",
        fg="#839496",
        surface="#073642",
        surface_light="#0a4050",
        border="#586e75",
        border_light="#657b83",
        accent="#268bd2",
        success="#859900",
        warning="#b58900",
        error="#dc322f",
    ),
    "monokai": ThemePalette(
        name="monokai",
        is_dark=True,
        bg="#272822",
        fg="#f8f8f2",
        surface="#3e3d32",
        surface_light="#49483e",
        border="#75715e",
        border_light="#a59f85",
        accent="#a6e22e",
        success="#a6e22e",
        warning="#e6db74",
        error="#f92672",
    ),
}


def get_palette(name: str) -> Optional[ThemePalette]:
    """Get a palette by name."""
    return BUILTIN_PALETTES.get(name)


def list_palettes() -> list[str]:
    """List all built-in palette names."""
    return sorted(BUILTIN_PALETTES.keys())


def get_default_palette() -> ThemePalette:
    """Get the default palette."""
    return BUILTIN_PALETTES["github-dark"]
