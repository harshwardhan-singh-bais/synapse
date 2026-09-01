"""Unified SQLite schema for Synapse (merges hcom, thurbox, kodo)."""

SCHEMA_VERSION = 2

SCHEMA_SQL = """
-- ─────────────────────────────────────────────────────────────────
-- sessions  (unified from thurbox + hcom)
-- ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sessions (
    id                  TEXT    PRIMARY KEY,       -- UUID
    name                TEXT    NOT NULL,
    agent               TEXT,                      -- agent name from agents.toml
    backend_id          TEXT,                      -- tmux pane id
    backend_type        TEXT,                      -- 'local-tmux' | 'ssh:<name>' | 'wsl:<name>'
    agent_session_id    TEXT,
    cwd                 TEXT,
    hook_state          TEXT,                      -- 'working' | 'blocked' | 'done' | 'idle'
    hook_state_at       INTEGER,                   -- epoch ms
    seen_at             INTEGER,
    tag                 TEXT,                      -- group label (from hcom)
    status              TEXT,                      -- 'active' | 'idle' | 'working' | 'blocked' | 'done' | 'error'
    pid                 INTEGER,
    hints               TEXT,
    display_order       INTEGER,
    parent_session_id   TEXT,
    created_at          INTEGER,
    updated_at          INTEGER,
    deleted_at          INTEGER
);

-- ─────────────────────────────────────────────────────────────────
-- worktrees
-- ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS worktrees (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT    REFERENCES sessions(id),
    repo_path       TEXT,
    worktree_path   TEXT,
    branch          TEXT,
    created_at      INTEGER,
    deleted_at      INTEGER
);

-- ─────────────────────────────────────────────────────────────────
-- messages  (merged hcom events + thurbox mailbox)
-- ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    to_session_id   TEXT,                          -- NULL = broadcast
    from_session_id TEXT,
    kind            TEXT,                          -- 'chat' | 'questions' | 'plan' | 'result' | 'status' | 'collision'
    body            TEXT,
    thread_id       TEXT,
    intent          TEXT,                          -- 'request' | 'inform' | 'ack'
    claimed_at      INTEGER,                       -- NULL = unclaimed (atomic exactly-once drain)
    wake_flag       INTEGER DEFAULT 0,
    created_at      INTEGER
);

-- ─────────────────────────────────────────────────────────────────
-- events  (hcom activity log)
-- ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT,
    type        TEXT,                              -- 'message' | 'status' | 'life' | 'file_edit' | 'tool_call'
    data        TEXT,                              -- JSON payload
    timestamp   INTEGER                            -- epoch ms
);

-- ─────────────────────────────────────────────────────────────────
-- subscriptions  (hcom subscribe rules)
-- ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS subscriptions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT,
    filter_type TEXT,                              -- 'message' | 'status' | 'file_edit'
    filter_spec TEXT,                              -- JSON
    created_at  INTEGER
);

-- ─────────────────────────────────────────────────────────────────
-- automations
-- ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS automations (
    id                      TEXT    PRIMARY KEY,   -- UUID
    name                    TEXT,
    enabled                 INTEGER DEFAULT 1,
    schedule_kind           TEXT,                  -- 'once' | 'cron'
    schedule_spec           TEXT,
    timezone                TEXT,
    action_kind             TEXT,                  -- 'send' | 'spawn' | 'exec'
    action_target_session   TEXT,
    action_repo_path        TEXT,
    action_worktree_branch  TEXT,
    action_base_branch      TEXT,
    action_agent            TEXT,
    action_command          TEXT,
    prompt                  TEXT,
    next_run_at             INTEGER,
    last_run_at             INTEGER,
    created_at              INTEGER,
    updated_at              INTEGER
);

-- ─────────────────────────────────────────────────────────────────
-- tasks
-- ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tasks (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    title                   TEXT,
    description             TEXT,
    status                  TEXT    DEFAULT 'todo', -- 'todo' | 'in_progress' | 'done'
    action_kind             TEXT,
    action_target_session   TEXT,
    action_repo_path        TEXT,
    action_worktree_branch  TEXT,
    action_base_branch      TEXT,
    action_agent            TEXT,
    action_command          TEXT,
    source                  TEXT    DEFAULT 'local',
    external_id             TEXT,
    external_url            TEXT,
    created_at              INTEGER,
    updated_at              INTEGER,
    deleted_at              INTEGER
);

-- ─────────────────────────────────────────────────────────────────
-- runs  (kodo orchestration runs)
-- ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS runs (
    id           TEXT    PRIMARY KEY,              -- UUID
    mode         TEXT,                             -- 'goal' | 'test' | 'improve' | 'fix-from' | 'resume'
    goal         TEXT,
    status       TEXT,                             -- 'running' | 'completed' | 'failed' | 'paused'
    effort       TEXT,                             -- 'low' | 'standard' | 'high' | 'max'
    team_name    TEXT,
    team_json    TEXT,                             -- full team config JSON
    plan_json    TEXT,                             -- GoalPlan JSON
    started_at   INTEGER,
    completed_at INTEGER,
    created_at   INTEGER
);

-- ─────────────────────────────────────────────────────────────────
-- stages  (kodo stages) — declared before cycles for FK reference
-- ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS stages (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              TEXT    REFERENCES runs(id),
    stage_index         INTEGER,
    name                TEXT,
    description         TEXT,
    acceptance_criteria TEXT,
    parallel_group      INTEGER,
    status              TEXT,                      -- 'pending' | 'running' | 'completed' | 'failed'
    verification        TEXT,                      -- 'full' | 'skip'
    started_at          INTEGER,
    completed_at        INTEGER
);

-- ─────────────────────────────────────────────────────────────────
-- cycles  (kodo cycle log)
-- ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS cycles (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT    REFERENCES runs(id),
    stage_id        INTEGER REFERENCES stages(id),
    cycle_index     INTEGER,
    exchanges       INTEGER,
    api_cost_usd    REAL,
    virtual_cost_usd REAL,
    summary         TEXT,
    finished        INTEGER DEFAULT 0,
    success         INTEGER DEFAULT 0,
    started_at      INTEGER,
    completed_at    INTEGER
);

-- ─────────────────────────────────────────────────────────────────
-- teams  (kodo custom teams)
-- ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS teams (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    UNIQUE,
    team_json   TEXT,
    created_at  INTEGER,
    updated_at  INTEGER
);

-- ─────────────────────────────────────────────────────────────────
-- cost_ledger
-- ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS cost_ledger (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT    REFERENCES runs(id),
    cycle_id    INTEGER REFERENCES cycles(id),
    bucket      TEXT,                              -- 'api' | 'claude_subscription' | 'cursor_subscription'
    amount_usd  REAL,
    model       TEXT,
    tokens_in   INTEGER,
    tokens_out  INTEGER,
    created_at  INTEGER
);

-- ─────────────────────────────────────────────────────────────────
-- relay_config  (hcom MQTT relay)
-- ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS relay_config (
    key     TEXT PRIMARY KEY,
    value   TEXT
);

-- ─────────────────────────────────────────────────────────────────
-- kv  (general key-value store)
-- ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS kv (
    key     TEXT PRIMARY KEY,
    value   TEXT
);

-- ─────────────────────────────────────────────────────────────────
-- automation_runs  (run history for automations)
-- ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS automation_runs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    automation_id       TEXT,
    automation_name     TEXT,
    action_kind         TEXT,
    fired_at            INTEGER,
    success             INTEGER DEFAULT 1,
    result              TEXT,
    error               TEXT,
    created_at          INTEGER
);

-- ─────────────────────────────────────────────────────────────────
-- knowledge_artifacts  (knowledge system read/write/list)
-- ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS knowledge_artifacts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    key         TEXT    UNIQUE,
    name        TEXT,
    content     TEXT,
    mime_type   TEXT,
    created_at  INTEGER,
    updated_at  INTEGER
);

-- ─────────────────────────────────────────────────────────────────
-- Indexes
-- ─────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_sessions_status         ON sessions(status);
CREATE INDEX IF NOT EXISTS idx_sessions_tag            ON sessions(tag);
CREATE INDEX IF NOT EXISTS idx_sessions_deleted_at     ON sessions(deleted_at);
CREATE INDEX IF NOT EXISTS idx_messages_to_session     ON messages(to_session_id);
CREATE INDEX IF NOT EXISTS idx_messages_from_session   ON messages(from_session_id);
CREATE INDEX IF NOT EXISTS idx_messages_claimed_at     ON messages(claimed_at);
CREATE INDEX IF NOT EXISTS idx_messages_thread_id      ON messages(thread_id);
CREATE INDEX IF NOT EXISTS idx_events_session_id       ON events(session_id);
CREATE INDEX IF NOT EXISTS idx_events_type             ON events(type);
CREATE INDEX IF NOT EXISTS idx_events_timestamp        ON events(timestamp);
CREATE INDEX IF NOT EXISTS idx_automations_enabled     ON automations(enabled);
CREATE INDEX IF NOT EXISTS idx_automations_next_run    ON automations(next_run_at);
CREATE INDEX IF NOT EXISTS idx_tasks_status            ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_deleted_at        ON tasks(deleted_at);
CREATE INDEX IF NOT EXISTS idx_runs_status             ON runs(status);
CREATE INDEX IF NOT EXISTS idx_cycles_run_id           ON cycles(run_id);
CREATE INDEX IF NOT EXISTS idx_stages_run_id           ON stages(run_id);
CREATE INDEX IF NOT EXISTS idx_cost_ledger_run_id      ON cost_ledger(run_id);
CREATE INDEX IF NOT EXISTS idx_automation_runs_id      ON automation_runs(automation_id);
CREATE INDEX IF NOT EXISTS idx_automation_runs_fired   ON automation_runs(fired_at);
CREATE INDEX IF NOT EXISTS idx_knowledge_artifacts_key ON knowledge_artifacts(key);
"""

# FTS5 virtual table for full-text search over messages and events.
# Content tables are external-content so we keep data in the real rows.
FTS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts
USING fts5(
    body,
    content='messages',
    content_rowid='id'
);

CREATE VIRTUAL TABLE IF NOT EXISTS events_fts
USING fts5(
    data,
    content='events',
    content_rowid='id'
);

-- Triggers to keep FTS indexes in sync with the real tables.

CREATE TRIGGER IF NOT EXISTS messages_fts_insert
AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, body) VALUES (new.id, new.body);
END;

CREATE TRIGGER IF NOT EXISTS messages_fts_delete
AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, body) VALUES ('delete', old.id, old.body);
END;

CREATE TRIGGER IF NOT EXISTS messages_fts_update
AFTER UPDATE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, body) VALUES ('delete', old.id, old.body);
    INSERT INTO messages_fts(rowid, body) VALUES (new.id, new.body);
END;

CREATE TRIGGER IF NOT EXISTS events_fts_insert
AFTER INSERT ON events BEGIN
    INSERT INTO events_fts(rowid, data) VALUES (new.id, new.data);
END;

CREATE TRIGGER IF NOT EXISTS events_fts_delete
AFTER DELETE ON events BEGIN
    INSERT INTO events_fts(events_fts, rowid, data) VALUES ('delete', old.id, old.data);
END;

CREATE TRIGGER IF NOT EXISTS events_fts_update
AFTER UPDATE ON events BEGIN
    INSERT INTO events_fts(events_fts, rowid, data) VALUES ('delete', old.id, old.data);
    INSERT INTO events_fts(rowid, data) VALUES (new.id, new.data);
END;
"""
