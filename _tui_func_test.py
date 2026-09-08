import asyncio, sys, tempfile, uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "synapse"))
from synapse.tui.app import SynapseApp
from synapse.core.config import SynapseConfig

async def run_case(label, seed_fn, keys):
    tmp = Path(tempfile.mkdtemp(prefix="synapse-func-"))
    cfg = SynapseConfig(db_path=tmp / "f.db")
    app = SynapseApp(cfg)
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause(0.8)
        await pilot.press("escape")
        await pilot.pause(0.6)
        seed_fn(app.db)
        try:
            for key in keys:
                await pilot.press(key)
                await pilot.pause(0.4)
            print(label, "OK")
        except Exception as e:
            print(label, "FAILED:", type(e).__name__)

def seed_task(db):
    db.execute("INSERT INTO tasks (title, description, status, source, created_at, updated_at) VALUES ('t1','d1','todo','tui',1,1)")
def seed_auto(db):
    db.execute("INSERT INTO automations (id, name, enabled, schedule_kind, schedule_spec, timezone, action_kind, prompt, next_run_at, created_at, updated_at) VALUES (?,?,1,'cron','0 9 * * *','UTC','send','x',1,1,1)", (str(uuid.uuid4()), "a1"))
def seed_event(db):
    db.execute("INSERT INTO events (session_id, type, data, timestamp) VALUES ('s1','message','{\"body\":\"hi\"}',1)")
def seed_artifact(db):
    db.execute("INSERT INTO knowledge_artifacts (key, name, content, mime_type, created_at, updated_at) VALUES ('k1','K','content','text/plain',1,1)")

async def main():
    await run_case("task+auto+art", lambda db: (seed_task(db), seed_auto(db), seed_artifact(db)), ["5","6","7"])
    await run_case("task+event+art", lambda db: (seed_task(db), seed_event(db), seed_artifact(db)), ["5","9","7"])
    await run_case("auto+event+art", lambda db: (seed_auto(db), seed_event(db), seed_artifact(db)), ["6","9","7"])

asyncio.run(main())
