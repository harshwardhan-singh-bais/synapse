"""
Task board — manage the Synapse task list from the TUI.

Left: task list (status glyph + title). Right: selected task detail.
Bottom bar: create / run / mark done / mark todo / delete.
"""

from __future__ import annotations

import threading
import time

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.widgets import Button, Label, ListItem, ListView, Static

from .. import theme

TASK_STATUS_STYLES = {
    "todo":        ("○", theme.TEXT_DIM),
    "in_progress": ("⟳", theme.YELLOW),
    "done":        ("✓", theme.GREEN),
}


def _ts_str(ms: int | None) -> str:
    if not ms:
        return "—"
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ms // 1000))


class TaskBoard(Static):
    """Task list + detail + action bar."""

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("  ✓ TASKS", id="tasks-title", classes="dashboard-title")
            with Horizontal(id="tasks-body"):
                with ScrollableContainer(id="tasks-list"):
                    yield Label("  All tasks", classes="panel-subtitle")
                    yield ListView(id="task-list")
                with Vertical(id="task-detail"):
                    yield Label("  Detail", classes="panel-subtitle")
                    yield Static(id="task-detail-content")
            with Horizontal(id="tasks-actions"):
                yield Button("＋ New", id="task-new-btn", variant="primary")
                yield Button("▶ Run", id="task-run-btn")
                yield Button("✓ Done", id="task-done-btn")
                yield Button("○ Todo", id="task-todo-btn")
                yield Button("⧉ Copy prompt", id="task-prompt-btn", tooltip="Copy the agent prompt for this task")
                yield Button("✗ Delete", id="task-delete-btn", variant="error")

    def on_mount(self) -> None:
        self._tasks: list[dict] = []
        self._selected_id: int | None = None
        self._update_title()
        self.refresh_tasks()
        self.set_interval(3.0, self.refresh_tasks)

    def _update_title(self) -> None:
        title = self.query_one("#tasks-title", Label)
        title.update(" ✓ TASKS")

    # ──────────────────────────────────────────────────────────────
    # Data
    # ──────────────────────────────────────────────────────────────

    def refresh_tasks(self) -> None:
        if not self.visible:
            return
        try:
            db = self.app.db  # type: ignore[attr-defined]
            rows = db.fetchall(
                "SELECT * FROM tasks WHERE deleted_at IS NULL ORDER BY created_at DESC LIMIT 100"
            )
            self._tasks = [dict(r) for r in rows]

            task_list = self.query_one("#task-list", ListView)
            task_list.clear()

            if not self._tasks:
                task_list.append(
                    ListItem(Label("  [dim italic]no tasks yet — press ＋ New[/]"))
                )
                self._render_detail(None)
                return

            for t in self._tasks:
                status = t.get("status") or "todo"
                glyph, color = TASK_STATUS_STYLES.get(status, (theme.TEXT_DIM, "·"))
                title = (t.get("title") or "(no title)")[:38]
                text = Text()
                text.append(f" {glyph} ", style=f"bold {color}")
                text.append(f"#{t['id']:<5}", style=f"dim {theme.TEXT_FAINT}")
                text.append(f"{title}", style=f"{theme.TEXT}")
                text.append(f"  [{status}]", style=f"bold {color}")
                item = ListItem(Label(text), id=f"task-{t['id']}")
                if t["id"] == self._selected_id:
                    item.add_class("selected-item")
                task_list.append(item)

            # Re-select if possible
            if self._selected_id is not None:
                self._render_detail(
                    next((t for t in self._tasks if t["id"] == self._selected_id), None)
                )
            elif self._tasks:
                self._selected_id = self._tasks[0]["id"]
                self._render_detail(self._tasks[0])
        except Exception:
            pass

    def _render_detail(self, task: dict | None) -> None:
        detail = self.query_one("#task-detail-content", Static)
        if task is None:
            detail.update(Text("\n  Select a task to inspect it.", style="dim italic"))
            return

        status = task.get("status") or "todo"
        glyph, color = TASK_STATUS_STYLES.get(status, (theme.TEXT_DIM, "·"))
        text = Text()
        text.append(f"  {glyph} #{task['id']}  ", style=f"bold {color}")
        text.append(f"{task.get('title') or '(no title)'}\n", style=f"bold {theme.TEXT}")
        text.append("  " + "─" * 46 + "\n\n", style=f"dim {theme.TEXT_FAINT}")

        text.append("  status    ", style=f"bold {theme.TEXT_DIM}")
        text.append(f"{status}\n", style=f"bold {color}")
        text.append("  created   ", style=f"bold {theme.TEXT_DIM}")
        text.append(f"{_ts_str(task.get('created_at'))}\n", style=f"dim {theme.TEXT_DIM}")
        text.append("  source    ", style=f"bold {theme.TEXT_DIM}")
        text.append(f"{task.get('source') or 'local'}\n", style=f"dim {theme.TEXT_DIM}")

        if task.get("description"):
            text.append("\n  description\n", style=f"bold {theme.TEXT_DIM}")
            text.append("  " + "─" * 46 + "\n", style=f"dim {theme.TEXT_FAINT}")
            for line in _wrap(task["description"], 46):
                text.append(f"  {line}\n", style=f"dim {theme.TEXT_DIM}")

        action_kind = task.get("action_kind")
        if action_kind:
            text.append(f"\n  action      ", style=f"bold {theme.TEXT_DIM}")
            text.append(f"{action_kind}\n", style=f"bold {theme.CYAN}")
            if task.get("action_target_session"):
                text.append("  target      ", style=f"bold {theme.TEXT_DIM}")
                text.append(f"{task['action_target_session'][:40]}\n", style=f"dim {theme.TEXT_DIM}")
            if task.get("action_repo_path"):
                text.append("  repo        ", style=f"bold {theme.TEXT_DIM}")
                text.append(f"{task['action_repo_path'][:40]}\n", style=f"dim {theme.TEXT_DIM}")
            if task.get("action_agent"):
                text.append("  agent       ", style=f"bold {theme.TEXT_DIM}")
                text.append(f"{task['action_agent']}\n", style=f"dim {theme.TEXT_DIM}")
            if task.get("action_command"):
                text.append("  command     ", style=f"bold {theme.TEXT_DIM}")
                text.append(f"{task['action_command'][:40]}\n", style=f"dim {theme.TEXT_DIM}")

        detail.update(text)

    # ──────────────────────────────────────────────────────────────
    # Selection
    # ──────────────────────────────────────────────────────────────

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item_id: str = event.item.id or ""
        if item_id.startswith("task-"):
            self._selected_id = int(item_id[5:])
            task = next((t for t in self._tasks if t["id"] == self._selected_id), None)
            self._render_detail(task)
            # Update highlight classes
            for child in self.query_one("#task-list", ListView).children:
                child.remove_class("selected-item")
            event.item.add_class("selected-item")

    # ──────────────────────────────────────────────────────────────
    # Actions
    # ──────────────────────────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "task-new-btn":
            self.app.action_new_task()  # type: ignore[attr-defined]
        elif btn_id in ("task-run-btn", "task-done-btn", "task-todo-btn", "task-delete-btn", "task-prompt-btn"):
            if self._selected_id is None:
                self.app.notify("No task selected.", severity="warning", timeout=2)  # type: ignore[attr-defined]
                return
            if btn_id == "task-run-btn":
                self._run_selected()
            elif btn_id == "task-done-btn":
                self._set_status("done")
            elif btn_id == "task-todo-btn":
                self._set_status("todo")
            elif btn_id == "task-delete-btn":
                self._delete_selected()
            elif btn_id == "task-prompt-btn":
                self._copy_prompt()

    def _set_status(self, status: str) -> None:
        try:
            db = self.app.db  # type: ignore[attr-defined]
            db.execute(
                "UPDATE tasks SET status=?, updated_at=? WHERE id=?",
                (status, db.now_ms(), self._selected_id),
            )
            self.app.notify(  # type: ignore[attr-defined]
                f"Task #{self._selected_id} → {status}",
                severity="information",
                timeout=2,
            )
            self.refresh_tasks()
        except Exception as exc:
            self.app.notify(str(exc), severity="error", timeout=4)  # type: ignore[attr-defined]

    def _delete_selected(self) -> None:
        try:
            db = self.app.db  # type: ignore[attr-defined]
            db.execute(
                "UPDATE tasks SET deleted_at=?, updated_at=? WHERE id=?",
                (db.now_ms(), db.now_ms(), self._selected_id),
            )
            self.app.notify(f"Task #{self._selected_id} deleted.", severity="warning", timeout=2)  # type: ignore[attr-defined]
            self._selected_id = None
            self.refresh_tasks()
        except Exception as exc:
            self.app.notify(str(exc), severity="error", timeout=4)  # type: ignore[attr-defined]

    def _copy_prompt(self) -> None:
        """Copy the generated agent prompt for the selected task to the clipboard."""
        task = next((t for t in self._tasks if t["id"] == self._selected_id), None)
        if task is None:
            return
        try:
            from ...cli.commands.task_cmds import _task_to_agent_prompt
            from ...session.models import TaskRecord

            record = TaskRecord.model_validate(task)
            prompt = _task_to_agent_prompt(record)
            from ...clipboard import copy_to_clipboard

            if copy_to_clipboard(prompt):
                self.app.notify(  # type: ignore[attr-defined]
                    "Task prompt copied to clipboard.",
                    severity="information",
                    timeout=3,
                )
            else:
                self.app.notify(  # type: ignore[attr-defined]
                    "Clipboard unavailable — prompt printed to log.",
                    severity="warning",
                    timeout=3,
                )
                self.app.log(prompt)  # type: ignore[attr-defined]
        except Exception as exc:
            self.app.notify(f"Copy failed: {exc}", severity="error", timeout=4)  # type: ignore[attr-defined]

    def _run_selected(self) -> None:
        task = next((t for t in self._tasks if t["id"] == self._selected_id), None)
        if task is None:
            return
        self.app.notify(  # type: ignore[attr-defined]
            f"Running task #{task['id']}…",
            severity="information",
            timeout=3,
        )
        threading.Thread(
            target=self._run_task_worker,
            args=(task,),
            daemon=True,
            name=f"task-run-{task['id']}",
        ).start()

    def _run_task_worker(self, task: dict) -> None:
        """Execute a task's action off the UI thread (mirrors `synapse task run`)."""
        app = self.app  # type: ignore[attr-defined]
        try:
            db = app.db
            db.execute(
                "UPDATE tasks SET status='in_progress', updated_at=? WHERE id=?",
                (db.now_ms(), task["id"]),
            )

            from ...backend.tmux import TmuxBackend
            from ...session.manager import SessionManager

            mgr = SessionManager(db, TmuxBackend(), app.config)
            success = True
            kind = task.get("action_kind") or ""

            if kind == "send":
                target = task.get("action_target_session")
                body = task.get("description") or task.get("title") or ""
                if target and body:
                    mgr.send_text(target, body)
                else:
                    success = False
            elif kind == "spawn":
                repo = task.get("action_repo_path")
                agent = task.get("action_agent") or app.config.default_agent
                branch = task.get("action_worktree_branch")
                if repo:
                    session = mgr.create_session(
                        name=f"task-{task['id']}",
                        repo_path=repo,
                        agent=agent,
                        worktree_branch=branch,
                        tag="task",
                    )
                    if task.get("description"):
                        mgr.send_text(session.id, task["description"])
                else:
                    success = False
            elif kind == "exec":
                cmd = task.get("action_command")
                if cmd:
                    import subprocess
                    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)  # noqa: S602
                    if result.returncode != 0:
                        success = False
                else:
                    success = False
            else:
                success = False

            final_status = "done" if success else "todo"
            db.execute(
                "UPDATE tasks SET status=?, updated_at=? WHERE id=?",
                (final_status, db.now_ms(), task["id"]),
            )
            msg = f"Task #{task['id']} completed." if success else f"Task #{task['id']} failed → todo"
            app.call_from_thread(app.notify, msg, severity="information" if success else "error", timeout=4)
        except Exception as exc:
            app.call_from_thread(
                app.notify, f"Task #{task['id']} error: {exc}", severity="error", timeout=5
            )
        finally:
            app.call_from_thread(self.refresh_tasks)


def _wrap(text: str, width: int) -> list[str]:
    """Simple word-wrap."""
    lines: list[str] = []
    while len(text) > width:
        cut = text.rfind(" ", 0, width)
        if cut == -1:
            cut = width
        lines.append(text[:cut])
        text = text[cut:].lstrip()
    lines.append(text)
    return lines