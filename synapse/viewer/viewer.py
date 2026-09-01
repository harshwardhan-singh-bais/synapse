"""
Interactive HTML viewer — replays JSONL run logs in a local web server.

Ported from kodo's viewer.py.
"""
from __future__ import annotations

import json
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, parse_qs


def generate_viewer_html(run_dir: Path) -> str:
    """Generate an HTML viewer for a run's JSONL log."""
    log_path = run_dir / "log.jsonl"
    if not log_path.exists():
        return "<html><body><h1>No log file found</h1></body></html>"

    events = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    events_json = json.dumps(events, indent=2, default=str)

    return f"""<!DOCTYPE html>
<html>
<head>
    <title>Synapse Run Viewer</title>
    <style>
        body {{ font-family: monospace; background: #0a0e14; color: #e6edf3; padding: 20px; }}
        h1 {{ color: #58a6ff; }}
        .event {{ margin: 5px 0; padding: 8px; border-left: 3px solid #30363d; background: #0d1117; }}
        .event.run_start {{ border-color: #58a6ff; }}
        .event.cycle_start {{ border-color: #3fb950; }}
        .event.cycle_end {{ border-color: #f85149; }}
        .event.verification_result {{ border-color: #d29922; }}
        .event.agent_call {{ border-color: #8b949e; }}
        .event.agent_result {{ border-color: #7ee787; }}
        .ts {{ color: #484f58; }}
        .event-type {{ color: #58a6ff; font-weight: bold; }}
        .event-data {{ color: #c9d1d9; white-space: pre-wrap; }}
        #controls {{ position: sticky; top: 0; background: #0a0e14; padding: 10px; border-bottom: 1px solid #21262d; }}
        button {{ background: #21262d; color: #c9d1d9; border: 1px solid #30363d; padding: 5px 15px; cursor: pointer; }}
        button:hover {{ background: #30363d; }}
        button.active {{ background: #1f6feb; border-color: #388bfd; }}
        .filter {{ margin: 5px; }}
    </style>
</head>
<body>
    <h1>⚡ Synapse Run Viewer</h1>
    <div id="controls">
        <strong>Filters:</strong>
        <button class="filter active" onclick="filterEvents('all')">All</button>
        <button class="filter" onclick="filterEvents('run_start')">Runs</button>
        <button class="filter" onclick="filterEvents('cycle_start')">Cycles</button>
        <button class="filter" onclick="filterEvents('verification_result')">Verification</button>
        <button class="filter" onclick="filterEvents('agent_call')">Agent Calls</button>
    </div>
    <div id="events"></div>
    <script>
        const events = {events_json};
        const container = document.getElementById('events');

        function renderEvents(filter) {{
            container.innerHTML = '';
            const filtered = filter === 'all' ? events : events.filter(e => e.event === filter);
            filtered.forEach(e => {{
                const div = document.createElement('div');
                div.className = 'event ' + (e.event || '');
                const ts = e.ts ? new Date(e.ts * 1000).toLocaleTimeString() : '';
                const data = JSON.stringify(e, null, 2).replace(/\\n/g, '<br>');
                div.innerHTML = `<span class="ts">${{ts}}</span> <span class="event-type">${{e.event || '?'}}</span><br><span class="event-data">${{data}}</span>`;
                container.appendChild(div);
            }});
        }}

        function filterEvents(filter) {{
            document.querySelectorAll('.filter').forEach(b => b.classList.remove('active'));
            event.target.classList.add('active');
            renderEvents(filter);
        }}

        renderEvents('all');
    </script>
</body>
</html>"""


def serve_viewer(run_dir: Path, port: int = 8765) -> None:
    """Start a local HTTP server to view the run log."""
    html = generate_viewer_html(run_dir)

    class Handler(SimpleHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(html.encode())

        def log_message(self, format, *args):
            pass  # Suppress logs

    server = HTTPServer(("127.0.0.1", port), Handler)
    print(f"  Viewer running at http://127.0.0.1:{port}")
    print("  Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped.")


def find_runs(runs_dir: Optional[Path] = None) -> list[dict]:
    """Find all available runs."""
    if runs_dir is None:
        from ..core.paths import RUNS_DIR
        runs_dir = RUNS_DIR

    runs = []
    if not runs_dir.exists():
        return runs

    for run_dir in sorted(runs_dir.iterdir(), reverse=True):
        if not run_dir.is_dir():
            continue
        log_path = run_dir / "log.jsonl"
        if not log_path.exists():
            continue

        # Count events
        event_count = 0
        first_ts = None
        last_ts = None
        for line in log_path.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
                event_count += 1
                ts = event.get("ts")
                if ts:
                    if first_ts is None or ts < first_ts:
                        first_ts = ts
                    if last_ts is None or ts > last_ts:
                        last_ts = ts
            except json.JSONDecodeError:
                continue

        runs.append({
            "id": run_dir.name,
            "path": str(run_dir),
            "events": event_count,
            "first_ts": first_ts,
            "last_ts": last_ts,
        })

    return runs
