"""
System panel — configuration, agents, plugins, scripts and workspaces.

Surfaces the operational subsystems that previously were CLI-only:
- config.toml summary (with validation issues from SynapseConfig.validate)
- agents.toml entries (name, command, backend)
- Lua plugins discovered by the plugin manager
- workflow scripts (builtins + user scripts)
- multi-repo workspaces
"""

from __future__ import annotations

from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.widgets import Button, Label, Static

from .. import theme


class SystemPanel(Static):
    """Everything operational about Synapse itself."""

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("  ⚙ System", id="system-title", classes="dashboard-title")
            with ScrollableContainer(id="system-scroll"):
                yield Static(id="system-content")
            with Horizontal(id="system-actions"):
                yield Button("⟳ Refresh", id="sys-refresh-btn")
                yield Button("Plugins dir", id="sys-plugins-btn")
                yield Button("Config dir", id="sys-config-btn")

    def on_mount(self) -> None:
        self.refresh_data()

    # ──────────────────────────────────────────────────────────────────
    # Data
    # ──────────────────────────────────────────────────────────────────

    def refresh_data(self) -> None:
        content = self.query_one("#system-content", Static)
        text = Text()

        # ── Config ────────────────────────────────────────────────────
        try:
            from ...core.config import SynapseConfig

            cfg = SynapseConfig.load()
            issues = cfg.validate()
            text.append("  CONFIG\n", style=f"bold {theme.ACCENT_HI}")
            text.append("  " + "─" * 58 + "\n", style=f"dim {theme.EDGE}")
            rows = [
                ("default agent", cfg.default_agent),
                ("effort", cfg.effort),
                ("terminal", cfg.terminal),
                ("max parallel", str(cfg.max_parallel)),
                ("auto approve", str(cfg.auto_approve)),
                ("auto subscribe", cfg.auto_subscribe),
                ("title mode", cfg.title_mode),
                ("db", str(cfg.db_path)),
            ]
            for k, v in rows:
                text.append(f"  {k:<16}", style=f"bold {theme.TEXT_DIM}")
                text.append(f"{v}\n", style=theme.TEXT)
            if issues:
                text.append(f"\n  ⚠ {len(issues)} config issue(s):\n", style=f"bold {theme.YELLOW}")
                for issue in issues[:6]:
                    text.append(f"   · {issue}\n", style=f"dim {theme.YELLOW}")
            else:
                text.append("\n  ✓ config valid\n", style=f"bold {theme.GREEN}")
            text.append("\n")
        except Exception as exc:
            text.append(f"  config error: {exc}\n\n", style=f"dim {theme.RED}")

        # ── Agents ────────────────────────────────────────────────────
        try:
            from ...core.config import load_agents_toml

            agents = load_agents_toml()
            text.append("  AGENTS (agents.toml)\n", style=f"bold {theme.ACCENT_HI}")
            text.append("  " + "─" * 58 + "\n", style=f"dim {theme.EDGE}")
            if not agents:
                text.append("  none defined — ~/.config/synapse/agents.toml\n", style="dim italic")
            for name, a in agents.items():
                color = theme.agent_color(name)
                text.append(f"  ● {name:<12}", style=f"bold {color}")
                text.append(f"{(a.command or name):<24}", style=theme.TEXT)
                text.append(f"{a.backend_type}\n", style=f"dim {theme.TEXT_FAINT}")
            text.append("\n")
        except Exception as exc:
            text.append(f"  agents error: {exc}\n\n", style=f"dim {theme.RED}")

        # ── Plugins ───────────────────────────────────────────────────
        try:
            from ...tui.plugins import HAS_LUA, PluginManager

            mgr = PluginManager()
            discovered = mgr.discover_plugins()
            text.append("  LUA PLUGINS\n", style=f"bold {theme.ACCENT_HI}")
            text.append("  " + "─" * 58 + "\n", style=f"dim {theme.EDGE}")
            text.append(f"  lua runtime: ", style=f"bold {theme.TEXT_DIM}")
            text.append(
                "available (lupa)\n" if HAS_LUA else "missing — pip install lupa\n",
                style=f"bold {theme.GREEN if HAS_LUA else theme.YELLOW}",
            )
            if not discovered:
                text.append(
                    "  no plugins in ~/.config/synapse/plugins/*.lua\n",
                    style="dim italic",
                )
            for p in discovered:
                text.append(f"  ▸ {p.name}\n", style=f"dim {theme.TEXT_DIM}")
            text.append("\n")
        except Exception as exc:
            text.append(f"  plugins error: {exc}\n\n", style=f"dim {theme.RED}")

        # ── Workflow scripts ──────────────────────────────────────────
        try:
            from ...scripts.runner import discover_scripts

            scripts = discover_scripts()
            text.append("  WORKFLOW SCRIPTS\n", style=f"bold {theme.ACCENT_HI}")
            text.append("  " + "─" * 58 + "\n", style=f"dim {theme.EDGE}")
            for s in scripts[:10]:
                text.append(f"  ▸ {s['name']:<14}", style=f"bold {theme.CYAN}")
                text.append(f"{s['description'][:44]}\n", style=f"dim {theme.TEXT_FAINT}")
            text.append("\n")
        except Exception as exc:
            text.append(f"  scripts error: {exc}\n\n", style=f"dim {theme.RED}")

        # ── Workspaces ────────────────────────────────────────────────
        try:
            from ...workspace.builder import list_workspaces

            spaces = list_workspaces()
            text.append("  MULTI-REPO WORKSPACES\n", style=f"bold {theme.ACCENT_HI}")
            text.append("  " + "─" * 58 + "\n", style=f"dim {theme.EDGE}")
            if not spaces:
                text.append("  none — build with synapse workspace build\n", style="dim italic")
            for ws in spaces[:6]:
                text.append(f"  ▸ {ws['session_id'][:12]:<14}", style=f"bold {theme.PURPLE}")
                text.append(f"{ws['repos']} repo(s)\n", style=f"dim {theme.TEXT_DIM}")

            content.update(text)
        except Exception as exc:
            text.append(f"  workspaces error: {exc}", style=f"dim {theme.RED}")
            content.update(text)

    # ──────────────────────────────────────────────────────────────────
    # Actions
    # ──────────────────────────────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "sys-refresh-btn":
            self.refresh_data()
        elif event.button.id == "sys-plugins-btn":
            self._reveal(Path.home() / ".config" / "synapse" / "plugins")
        elif event.button.id == "sys-config-btn":
            from ...core.paths import CONFIG_DIR

            self._reveal(Path(CONFIG_DIR))

    @staticmethod
    def _reveal(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        try:
            import subprocess
            import sys

            if sys.platform.startswith("win"):
                subprocess.Popen(["explorer", str(path)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception:
            pass
