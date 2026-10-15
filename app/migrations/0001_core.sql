-- Core tables: settings, scheduler, files, jobs, AI call journal, model registry.

CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value_json TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE scheduler_runs (
    name TEXT PRIMARY KEY,
    last_run TEXT
);

CREATE TABLE files (
    id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL,
    kind TEXT NOT NULL,              -- image | video | audio | font | other
    mime TEXT,
    ext TEXT,
    path TEXT NOT NULL UNIQUE,       -- relative to the data dir
    size_bytes INTEGER,
    width INTEGER,
    height INTEGER,
    duration REAL,
    sha256 TEXT,
    origin TEXT NOT NULL DEFAULT 'generated',  -- upload | generated | derived | system
    is_service INTEGER NOT NULL DEFAULT 0,     -- intermediate file, not shown in the library
    title TEXT,
    original_name TEXT,
    source_type TEXT,
    source_id INTEGER,
    poster_path TEXT,
    preview_path TEXT,
    meta_json TEXT
);
CREATE INDEX idx_files_created ON files (created_at);
CREATE INDEX idx_files_kind ON files (kind, is_service);
CREATE INDEX idx_files_source ON files (source_type, source_id);

CREATE TABLE jobs (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    group_name TEXT NOT NULL,
    status TEXT NOT NULL,            -- queued | running | done | error | cancelled | interrupted
    priority INTEGER NOT NULL DEFAULT 0,
    serial_key TEXT,
    title TEXT,
    ref_type TEXT,
    ref_id INTEGER,
    payload_json TEXT,
    state_json TEXT,
    result_json TEXT,
    progress REAL,
    progress_note TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    error_code TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);
CREATE INDEX idx_jobs_status ON jobs (status, priority, id);
CREATE INDEX idx_jobs_ref ON jobs (ref_type, ref_id);

-- Every paid (and unpaid) Google call. One row per attempt.
CREATE TABLE ai_calls (
    id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL,
    finished_at TEXT,
    duration_ms INTEGER,
    attempt INTEGER NOT NULL DEFAULT 1,
    kind TEXT NOT NULL,              -- text | image | video | list_models | token ...
    purpose TEXT NOT NULL,           -- frame, frame_edit, regions, video_clip, connection_check ...
    role TEXT,
    model_id TEXT,
    region TEXT,
    price_snapshot_json TEXT,
    prompt_code TEXT,
    prompt_version INTEGER,
    prompt_text TEXT,
    request_json TEXT,
    attachments_json TEXT,
    response_json TEXT,
    tokens_in INTEGER,
    tokens_out INTEGER,
    tokens_thinking INTEGER,
    video_seconds REAL,
    video_resolution TEXT,
    input_video_seconds REAL,
    output_video_seconds REAL,
    search_queries INTEGER,
    cost_usd REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL,            -- running | success | error | blocked | cancelled
    error_code TEXT,
    error_text TEXT,
    http_status INTEGER,
    operation_name TEXT,
    stub INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_ai_calls_created ON ai_calls (created_at);
CREATE INDEX idx_ai_calls_kind ON ai_calls (kind, purpose);
CREATE INDEX idx_ai_calls_model ON ai_calls (model_id);
CREATE INDEX idx_ai_calls_status ON ai_calls (status);

CREATE TABLE ai_call_refs (
    call_id INTEGER NOT NULL REFERENCES ai_calls (id) ON DELETE CASCADE,
    ref_type TEXT NOT NULL,
    ref_id INTEGER NOT NULL,
    PRIMARY KEY (call_id, ref_type, ref_id)
);
CREATE INDEX idx_ai_call_refs_ref ON ai_call_refs (ref_type, ref_id);

-- Model registry. Seeded from seeds/models.json; user edits live in user_*_json
-- and the flags, and survive re-seeding.
CREATE TABLE models (
    id TEXT PRIMARY KEY,             -- Vertex model id
    kind TEXT NOT NULL,              -- image | video | text
    title TEXT NOT NULL,
    region TEXT NOT NULL DEFAULT 'global',
    api TEXT NOT NULL DEFAULT 'generate_content',  -- generate_content | veo | omni
    sort INTEGER NOT NULL DEFAULT 0,
    seed_json TEXT NOT NULL,         -- the full seed record (prices, capabilities)
    user_price_json TEXT,            -- price overrides by the user
    enabled INTEGER NOT NULL DEFAULT 1,
    is_default INTEGER NOT NULL DEFAULT 0,
    user_touched_default INTEGER NOT NULL DEFAULT 0,
    available INTEGER,               -- NULL unknown, 1 yes, 0 no (last connection check)
    available_checked_at TEXT,
    removed_from_seed INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE role_models (
    role TEXT PRIMARY KEY,
    model_id TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
