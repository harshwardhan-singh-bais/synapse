"""Headless smoke test for the redesigned Synapse TUI (not committed)."""
import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "synapse"))

from synapse.tui.app import SynapseApp
from synapse.core.config import SynapseConfig


async def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="synapse-smoke-"))
    cfg = SynapseConfig(db_path=tmp / "smoke.db")
    app = SynapseApp(cfg)
    async with app.run_test(size=(132, 44)) as pilot:
        await pilot.pause(1.2)
        print("on boot:", type(app.screen).__name__)
        await pilot.press("escape")  # skips boot
        await pilot.pause(0.6)
        print("after boot:", type(app.screen).__name__)
        await pilot.pause(0.4)
        # All utility tabs (0 = system added, 8 = transcripts, 9 = hooks)
        for key, name in [("1", "overview"), ("2", "sessions"), ("3", "orchestration"),
                          ("4", "mailbox"), ("5", "tasks"), ("6", "automations"),
                          ("7", "knowledge"), ("8", "transcripts"), ("9", "hooks"),
                          ("0", "system")]:
            await pilot.press(key)
            await pilot.pause(0.4)
            assert app.query_one("#main-tabs").active == name, f"tab {key} -> {name}"
            print(f"tab {key} ->", name)
        # Help overlay
        await pilot.press("question_mark")
        await pilot.pause(0.4)
        print("help overlay:", type(app.screen).__name__)
        await pilot.press("escape")
        await pilot.pause(0.3)
        # Modals
        await pilot.press("t")  # new task
        await pilot.pause(0.4)
        print("new-task modal:", type(app.screen).__name__)
        await pilot.press("escape")
        await pilot.pause(0.3)
        await pilot.press("a")  # new automation
        await pilot.pause(0.4)
        print("new-auto modal:", type(app.screen).__name__)
        await pilot.press("escape")
        await pilot.pause(0.3)
        await pilot.press("o")  # orchestrate modal
        await pilot.pause(0.4)
        print("orchestrate modal:", type(app.screen).__name__)
        await pilot.press("escape")
        await pilot.pause(0.3)
        # Slash command via command bar
        from textual.widgets import Input

        inp = app.query_one("#cmd-input", Input)
        inp.focus()
        await pilot.pause(0.3)
        inp.value = "/task smoke-cmd-task"
        await pilot.pause(0.2)
        await pilot.press("enter")
        await pilot.pause(0.8)
        row = app.db.fetchone("SELECT title FROM tasks WHERE title='smoke-cmd-task'")
        print("slash /task:", row["title"] if row else None)
        assert row is not None, "slash /task did not create a task"
        # Confirm dialog on delete (no session selected -> warning only)
        from textual.widgets import Input as _In

        app.query_one("#cmd-input", _In).blur()
        await pilot.pause(0.3)
        await pilot.press("f6")  # perf hud
        await pilot.pause(0.4)
        await pilot.press("f6")
        await pilot.pause(0.4)
        await pilot.press("f5")  # refresh all
        await pilot.pause(0.5)
        print("SMOKE_OK")


asyncio.run(main())