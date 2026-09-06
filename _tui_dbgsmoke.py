"""Diagnostic run_test harness for the Synapse TUI (not committed)."""
import asyncio
import sys
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "synapse"))

from synapse.tui.app import SynapseApp
from synapse.core.config import SynapseConfig


async def scenario(which: str) -> None:
    tmp = Path(tempfile.mkdtemp(prefix="synapse-smoke-"))
    cfg = SynapseConfig(db_path=tmp / "smoke.db")
    app = SynapseApp(cfg)

    # Surface any unhandled exception that Textual catches.
    original = app.call_later
    app._errors = []

    def _on_unhandled(exc):
        app._errors.append(exc)

    app._exception_callback = _on_unhandled  # best effort

    async with app.run_test(size=(132, 44)) as pilot:
        await pilot.pause(1.0)
        print("[step] boot ok", flush=True)
        await pilot.press("q")
        await pilot.pause(0.4)
        print("[step] boot skipped", flush=True)

        if which in ("simple",):
            await pilot.pause(2.0)
            print("[step] idle 2s ok", flush=True)
        elif which == "tabs":
            await pilot.press("2")
            await pilot.pause(0.8)
            print("[step] tab runs ok", flush=True)
            await pilot.press("3")
            await pilot.pause(0.8)
            print("[step] tab mailbox ok", flush=True)
            await pilot.press("1")
            await pilot.pause(0.8)
            print("[step] tab sessions ok", flush=True)
        elif which == "showcase":
            await pilot.press("l")
            await pilot.pause(0.6)
            print("[step] showcase opened", flush=True)
            await pilot.press("q")
            await pilot.pause(0.4)
            print("[step] showcase closed", flush=True)
        elif which == "modal":
            await pilot.press("n")
            await pilot.pause(0.6)
            print("[step] modal opened", flush=True)
            await pilot.press("escape")
            await pilot.pause(0.4)
            print("[step] modal closed", flush=True)

        await app.exit()
        await pilot.pause(0.4)
    print("[step] exiting context, smoke DONE", flush=True)
    if getattr(app, "_errors", None):
        print("ERRORS DETECTED:", app._errors, flush=True)
    else:
        print("NO ERRORS", flush=True)


async def main() -> None:
    which = sys.argv[1] if len(sys.argv) > 1 else "simple"
    try:
        await asyncio.wait_for(scenario(which), timeout=25)
    except asyncio.TimeoutError:
        print("HANG DETECTED in", which, flush=True)
        for task in asyncio.all_tasks():
            task.print_stack(limit=20)
    except Exception:
        traceback.print_exc()


asyncio.run(main())