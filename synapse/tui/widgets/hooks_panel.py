"""
Hooks panel — install / verify / remove Synapse hooks for every agent tool.

Covers Claude, Gemini, Codex, Cursor, OpenCode, Pi, OMP and Antigravity,
plus the thurbox-style lifecycle hooks from ``hooks.toml``.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.widgets import Button, DataTable, Label, Static

from .. import theme


class HooksPanel(Static):
    """Per-tool hook status table + lifecycle hooks + action bar."""

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("  ⛓ Hooks", id="hooks-title", classes="dashboard-title")
            with ScrollableContainer(id="hooks-table-wrap"):
                table = DataTable(id="hooks-table", zebra_stripes=True)
                table.cursor_type = "row"
                yield table
            with Vertical(id="hooks-lifecycle"):
                yield Label("  Lifecycle hooks (hooks.toml)", classes="panel-subtitle")
                yield Static(id="hooks-lifecycle-content")
            with Horizontal(id="hooks-actions"):
                yield Button("⬇ Install all", id="hooks-install-btn", variant="primary")
                yield Button("✓ Verify all", id="hooks-verify-btn")
                yield Button("✗ Remove (claude)", id="hooks-remove-btn", variant="error")
                yield Button("⟳ Refresh", id="hooks-refresh-btn")

    def on_mount(self) -> None:
        table = self.query_one("#hooks-table", DataTable)
        table.add_columns("Tool", "Config file", "Status")
        self.refresh_hooks()

    # ──────────────────────────────────────────────────────────────────
    # Data
    # ──────────────────────────────────────────────────────────────────

    def _tool_rows(self) -> list[tuple[str, object, object]]:
        """(tool, installed_checker, installer) per supported tool."""
        from ...hooks.registry import HookInstaller

        inst = HookInstaller()
        return [
            ("claude",     inst.verify_claude_hooks,    inst.install_claude_hooks),
            ("gemini",     self._check_json("~/.gemini/settings.json"),  inst.install_gemini_hooks),
            ("codex",      self._check_toml("~/.codex/config.toml"),     inst.install_codex_hooks),
            ("cursor",     self._check_json("~/.cursor/hooks.json"),     inst.install_cursor_hooks),
            ("opencode",   self._check_json("~/.opencode/hooks.json"),   inst.install_opencode_hooks),
            ("pi",         self._check_json("~/.pi/settings.json"),      inst.install_pi_hooks),
            ("omp",        self._check_toml("~/.omp/config.toml"),       inst.install_omp_hooks),
            ("antigravity", self._check_json("~/.antigravity/hooks.json"), inst.install_antigravity_hooks),
        ]

    @staticmethod
    def _check_json(rel: str):
        from pathlib import Path

        def check() -> bool:
            p = Path.home() / rel.lstrip("~/")
            if not p.exists():
                return False
            try:
                import json

                data = json.loads(p.read_text(encoding="utf-8"))
                return "synapse" in json.dumps(data).lower()
            except Exception:
                return False
        return check

    @staticmethod
    def _check_toml(rel: str):
        from pathlib import Path

        def check() -> bool:
            p = Path.home() / rel.lstrip("~/")
            if not p.exists():
                return False
            try:
                return "synapse" in p.read_text(encoding="utf-8").lower()
            except Exception:
                return False
        return check

    def refresh_hooks(self) -> None:
        table = self.query_one("#hooks-table", DataTable)
        table.clear()
        for tool, checker, _ in self._tool_rows():
            try:
                installed = bool(checker())
            except Exception:
                installed = False
            status = Text("● installed", style=f"bold {theme.GREEN}") if installed else Text(
                "○ not installed", style=f"dim {theme.TEXT_FAINT}"
            )
            table.add_row(f" {tool}", self._config_hint(tool), status)
        self._render_lifecycle()

    @staticmethod
    def _config_hint(tool: str) -> str:
        hints = {
            "claude": "~/.claude/settings.json",
            "gemini": "~/.gemini/settings.json",
            "codex": "~/.codex/config.toml",
            "cursor": "~/.cursor/hooks.json",
            "opencode": "~/.opencode/hooks.json",
            "pi": "~/.pi/settings.json",
            "omp": "~/.omp/config.toml",
            "antigravity": "~/.antigravity/hooks.json",
        }
        return hints.get(tool, "?")

    def _render_lifecycle(self) -> None:
        content = self.query_one("#hooks-lifecycle-content", Static)
        try:
            from ...hooks.registry import load_hooks_toml

            hooks = load_hooks_toml()
            text = Text()
            if not hooks:
                text.append(
                    "  No lifecycle hooks configured.\n"
                    "  Add ~/.config/synapse/hooks.toml with [pre_create] / [post_create] … sections.\n",
                    style=f"dim {theme.TEXT_FAINT}",
                )
            else:
                for event, hook_list in sorted(hooks.items()):
                    text.append(f"  {event:<14}", style=f"bold {theme.CYAN}")
                    text.append(f"{len(hook_list)} hook(s)\n", style=f"dim {theme.TEXT_DIM}")
            content.update(text)
        except Exception as exc:
            content.update(Text(f"  error: {exc}", style=f"dim {theme.RED}"))

    # ──────────────────────────────────────────────────────────────────
    # Actions
    # ──────────────────────────────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn = event.button.id
        from ...hooks.registry import HookInstaller

        inst = HookInstaller()
        if btn == "hooks-install-btn":
            results = inst.install_all_hooks()
            ok = sum(1 for v in results.values() if v)
            self.app.notify(  # type: ignore[attr-defined]
                f"Hooks installed for {ok}/{len(results)} tools.",
                severity="information",
                timeout=4,
            )
            self.refresh_hooks()
        elif btn == "hooks-verify-btn":
            results = {
                tool: bool(checker())
                for tool, checker, _ in self._tool_rows()
            }
            ok = sum(1 for v in results.values() if v)
            self.app.notify(  # type: ignore[attr-defined]
                f"{ok}/{len(results)} tools have Synapse hooks installed.",
                severity="information",
                timeout=4,
            )
            self.refresh_hooks()
        elif btn == "hooks-remove-btn":
            results = inst.remove_all_hooks()
            ok = sum(1 for v in results.values() if v)
            self.app.notify(  # type: ignore[attr-defined]
                f"Removed hooks for {ok} tool(s).",
                severity="warning",
                timeout=4,
            )
            self.refresh_hooks()
        elif btn == "hooks-refresh-btn":
            self.refresh_hooks()
