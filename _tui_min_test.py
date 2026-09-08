import asyncio
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import Static, Footer

class Boot(ModalScreen[None]):
    BINDINGS = [("escape", "skip", "Skip boot")]
    def on_mount(self):
        self.set_timer(3.0, self._finish)
    def _finish(self):
        self.dismiss(None)
    def action_skip(self):
        print("skip via binding")
        self.dismiss(None)
    def compose(self) -> ComposeResult:
        yield Static("BOOT")

class T(App):
    BINDINGS = [Binding("5", "five", "Five", show=True), Binding("q", "quit", "Quit", show=True)]
    def compose(self) -> ComposeResult:
        yield Static("MAIN")
        yield Footer()
    def on_mount(self):
        self.push_screen(Boot())
    def action_five(self):
        print(">>> FIVE FIRED")

async def main():
    app = T()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause(0.6)
        await pilot.press("escape")
        await pilot.pause(0.5)
        print("screen:", type(app.screen).__name__)
        await pilot.press("5")
        await pilot.pause(0.4)
        print("done")

asyncio.run(main())
