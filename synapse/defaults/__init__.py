"""Default configuration templates for Synapse."""
from __future__ import annotations

from pathlib import Path

DEFAULTS_DIR = Path(__file__).parent


def install_defaults(config_dir: Path) -> list[Path]:
    """
    Copy default ``*.toml`` templates into *config_dir* if they don't already exist.

    Returns a list of files that were actually written (skips pre-existing ones).
    """
    config_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for template in sorted(DEFAULTS_DIR.glob("*.toml")):
        dest = config_dir / template.name
        if not dest.exists():
            dest.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
            written.append(dest)
    return written
