import asyncio, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "synapse"))
from synapse.tui.app import SynapseApp
from synapse.core.config import SynapseConfig

class FakeBtn:
    def __init__(self, bid): self.id = bid
class FakeEvent:
    def __init__(self, bid): self.button = FakeBtn(bid)

async def main():
    tmp = Path(tempfile.mkdtemp(prefix="synapse-e2e-"))
    cfg = SynapseConfig(db_path=tmp / "e.db")
    app = SynapseApp(cfg)
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause(0.8)
        await pilot.press("escape")
        await pilot.pause(0.6)
        db = app.db

        # Task modal
        await pilot.press("t")
        await pilot.pause(0.5)
        s = app.screen
        s.query_one("#title-input").value = "refactor-auth"
        s.query_one("#desc-input").text = "do the thing"
        s.on_button_pressed(FakeEvent("create-btn"))
        await asyncio.sleep(0.4)
        row = db.fetchone("SELECT * FROM tasks ORDER BY id DESC LIMIT 1")
        print("task:", row["title"] if row else None, "| action:", row["action_kind"] if row else None)

        # Automation modal (uses preset daily trigger)
        await pilot.press("6")
        await pilot.pause(0.5)
        await pilot.press("a")
        await pilot.pause(0.5)
        s2 = app.screen
        s2.query_one("#name-input").value = "nightly-cleanup"
        s2.query_one("#prompt-input").text = "clean up"
        s2.on_button_pressed(FakeEvent("create-btn"))
        await asyncio.sleep(0.4)
        r2 = db.fetchone("SELECT * FROM automations ORDER BY created_at DESC LIMIT 1")
        print("automation:", r2["name"] if r2 else None, "| sched:", r2["schedule_spec"] if r2 else None, "| action:", r2["action_kind"] if r2 else None)

        # Artifact modal
        await pilot.press("7")
        await pilot.pause(0.5)
        app.run_worker(app.action_new_artifact(), group="e2e")
        await pilot.pause(0.5)
        s3 = app.screen
        s3.query_one("#key-input").value = "design/session-flow"
        s3.query_one("#content-input").text = "sessions are claim-based"
        s3.on_button_pressed(FakeEvent("create-btn"))
        await asyncio.sleep(0.4)
        art = db.fetchone("SELECT * FROM knowledge_artifacts ORDER BY id DESC LIMIT 1")
        print("artifact:", art["key"] if art else None)

        # Orchestrate modal submit
        await pilot.press("o")
        await pilot.pause(0.5)
        s4 = app.screen
        s4.query_one("#goal-input").text = "verify everything"
        s4.on_button_pressed(FakeEvent("create-btn"))
        await asyncio.sleep(0.4)
        print("orchestrate dismissed ->", type(app.screen).__name__)
        print("E2E_DONE")

asyncio.run(main())
