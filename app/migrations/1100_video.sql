-- Module 11: video. A run is one video being made: the brief, frames and references,
-- settings, the clips Google made for it and the versions of the finished video.

CREATE TABLE video_runs (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    niche TEXT NOT NULL DEFAULT '',              -- what is advertised (<= 120 chars), for "write it for me"
    platform TEXT NOT NULL DEFAULT '',           -- where it will be posted, for the research
    brief TEXT NOT NULL DEFAULT '',              -- the text that is filmed, sent verbatim
    brief_meta_json TEXT,                        -- {seconds, aspect, niche, photo, researched, written_at, replaced}
    first_frame_id INTEGER REFERENCES files (id) ON DELETE SET NULL,
    last_frame_id INTEGER REFERENCES files (id) ON DELETE SET NULL,
    references_json TEXT NOT NULL DEFAULT '[]',  -- [file_id, ...]
    storyboard_json TEXT,                        -- {file_id, prompt, attached, own, panels}
    model_id TEXT,
    duration INTEGER,
    resolution TEXT,
    aspect TEXT,
    camera_move TEXT NOT NULL DEFAULT '',
    sound INTEGER NOT NULL DEFAULT 1,
    stage TEXT NOT NULL DEFAULT 'draft',         -- draft | take | extend | done
    status TEXT NOT NULL DEFAULT 'idle',         -- idle | running | done | error | paused
    error_code TEXT,
    error TEXT,
    result_file_id INTEGER REFERENCES files (id) ON DELETE SET NULL,
    current_version INTEGER,                     -- number in video_versions
    results_json TEXT NOT NULL DEFAULT '[]',     -- history of result files [{file_id, version, at}]
    extend_plan_json TEXT,                       -- several extensions: {steps, done, pause_each, model_id, ...}
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_video_runs_updated ON video_runs (updated_at);

CREATE TABLE video_clips (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES video_runs (id) ON DELETE CASCADE,
    number INTEGER NOT NULL,
    kind TEXT NOT NULL,                          -- take | extend | continue
    model_id TEXT,
    prompt TEXT,                                 -- exactly what went to the model
    operation_name TEXT,                         -- Veo long operation, to resume after a restart
    call_id INTEGER,                             -- ai_calls row of the request
    job_id INTEGER,
    status TEXT NOT NULL DEFAULT 'queued',       -- queued | running | done | error | cancelled
    archived INTEGER NOT NULL DEFAULT 0,         -- 1 after a new "Start": kept, not shown as current
    file_id INTEGER REFERENCES files (id) ON DELETE SET NULL,   -- the model's answer
    seconds REAL,                                -- asked of the model
    resolution TEXT,
    aspect TEXT,
    cost_usd REAL,
    error_code TEXT,
    error TEXT,
    next_text TEXT,                              -- extension: "what happens next"
    tail_start REAL,                             -- extension: second of the source where the tail starts
    tail_seconds REAL,                           -- extension: tail length sent to the model
    seconds_added REAL,                          -- extension: seconds asked to add
    seconds_received REAL,                       -- extension: seconds actually added
    source_version INTEGER,                      -- extension: version that was extended
    meta_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_video_clips_run ON video_clips (run_id, number);
CREATE INDEX idx_video_clips_status ON video_clips (status);
CREATE INDEX idx_video_clips_file ON video_clips (file_id);

CREATE TABLE video_versions (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES video_runs (id) ON DELETE CASCADE,
    number INTEGER NOT NULL,
    kind TEXT NOT NULL DEFAULT 'take',           -- take | extend | continue
    file_id INTEGER REFERENCES files (id) ON DELETE SET NULL,
    duration REAL,
    clip_ids_json TEXT NOT NULL DEFAULT '[]',    -- clips this version is built from
    archived INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE (run_id, number)
);
CREATE INDEX idx_video_versions_file ON video_versions (file_id);

-- "Write it for me": the niche research is reused for 14 days.
CREATE TABLE video_research (
    id INTEGER PRIMARY KEY,
    niche_key TEXT NOT NULL,
    platform TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL,
    model_id TEXT,
    cost_usd REAL,
    created_at TEXT NOT NULL,
    UNIQUE (niche_key, platform)
);
