import asyncio, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "synapse"))
from synapse.tui.app import SynapseApp
from synapse.core.config import SynapseConfig
from textual.screen import ModalScreen
from synapse.tui.screens.new_task_screen import NewTaskScreen
from synapse.tui.screens.orchestrate_screen import OrchestrateScreen

async def main():
    tmp = Path(tempfile.mkdtemp(prefix="synapse-modal-"))
    cfg = SynapseConfig(db_path=tmp / "m.db")
    app = SynapseApp(cfg)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.8)
        await pilot.press("q")
        await pilot.pause(0.4)
        await pilot.press("t")
        await pilot.pause(0.5)
        print("after t:", type(app.screen).__name__, "modal?", isinstance(app.screen, ModalScreen))
        await pilot.press("escape")
        await pilot.pause(0.4)
        await pilot.press("o")
        await pilot.pause(0.5)
        print("after o:", type(app.screen).__name__, "modal?", isinstance(app.screen, ModalScreen))

asyncio.run(main())
