import asyncio, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "synapse"))
from synapse.tui.app import SynapseApp
from synapse.core.config import SynapseConfig
import textual.app as ta

orig = ta.App._check_bindings
async def patched(self, key, priority=False):
    print(">>> _check_bindings key=", key, "priority=", priority)
    return await orig(self, key, priority)
ta.App._check_bindings = patched

async def main():
    tmp = Path(tempfile.mkdtemp(prefix="synapse-bind-"))
    cfg = SynapseConfig(db_path=tmp / "b.db")
    app = SynapseApp(cfg)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.8)
        await pilot.press("q")   # dismiss boot
        await pilot.pause(0.5)
        print("screen after boot:", type(app.screen).__name__)
        print("focused:", app.focused)
        await pilot.press("x")   # unbound key
        await pilot.pause(0.4)
        await pilot.press("q")   # should quit
        await pilot.pause(0.6)
        print("alive after q:", app._exit)

asyncio.run(main())
