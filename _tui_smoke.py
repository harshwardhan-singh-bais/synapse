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
        await pilot.press("q")  # skips boot
        await pilot.pause(0.6)
        print("after boot:", type(app.screen).__name__)
        await pilot.pause(0.4)
        await pilot.press("2")  # runs tab
        await pilot.pause(0.9)
        print("after press 2")
        await pilot.press("3")  # mailbox
        await pilot.pause(0.9)
        print("after press 3")
        await pilot.press("1")  # sessions tab
        await pilot.pause(0.9)
        print("after press 1")
        await pilot.press("l")  # loader showcase
        await pilot.pause(0.6)
        print("showcase:", type(app.screen).__name__)
        await pilot.press("q")
        await pilot.pause(0.4)
        await pilot.press("f6")  # perf hud
        await pilot.pause(0.4)
        await pilot.press("f6")
        await pilot.pause(0.3)
        await pilot.press("n")  # new session modal
        await pilot.pause(0.6)
        print("modal:", type(app.screen).__name__)
        await pilot.press("escape")
        await pilot.pause(0.5)
        await pilot.press("q")  # quit app
        await pilot.pause(0.6)
        print("SMOKE_OK")


asyncio.run(main())