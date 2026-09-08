import asyncio, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "synapse"))
from synapse.tui.app import SynapseApp
from synapse.core.config import SynapseConfig

async def main():
    tmp = Path(tempfile.mkdtemp(prefix="synapse-focus-"))
    cfg = SynapseConfig(db_path=tmp / "f.db")
    app = SynapseApp(cfg)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.8)
        await pilot.press("q")
        await pilot.pause(0.5)
        print("focused:", app.focused)
        tabs = app.query_one("#main-tabs")
        print("tabs active:", tabs.active)
        await pilot.press("5")
        await pilot.pause(0.5)
        print("after 5, tabs active:", tabs.active)
        await pilot.press("t")
        await pilot.pause(0.5)
        print("after t, screen:", type(app.screen).__name__)

asyncio.run(main())
