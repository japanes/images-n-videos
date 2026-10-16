-- Module 04: image studio. A work is a set of frames with shared settings;
-- a frame is one picture with its own brief, overrides and version history.

CREATE TABLE image_works (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    kit_id INTEGER REFERENCES brand_kits (id) ON DELETE SET NULL,  -- NULL = no brand
    brand_json TEXT,                          -- brand.snapshot_kit() taken when the kit was picked
    model_id TEXT,                            -- NULL = the registry default for pictures
    aspect TEXT NOT NULL DEFAULT '1:1',
    image_size TEXT NOT NULL DEFAULT '1K',    -- 1K | 2K | 4K (what the model allows)
    frame_count INTEGER NOT NULL DEFAULT 1,
    -- {references: [file_id], subjects: [id], photo_style, style, style_sample, text_mode,
    --  blocks: {code: bool}, ideas_brief, series, pilot_frame_id, feedback}
    settings_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'draft',     -- draft | active | archived
    archived_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_image_works_list ON image_works (status, updated_at);

CREATE TABLE frames (
    id INTEGER PRIMARY KEY,
    work_id INTEGER NOT NULL REFERENCES image_works (id) ON DELETE CASCADE,
    position INTEGER NOT NULL DEFAULT 0,
    brief TEXT NOT NULL DEFAULT '',
    -- per-frame overrides: {model_id, image_size, references, subjects, photo_style, text_mode}
    overrides_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'empty',     -- empty | queued | drawing | done | error
    file_id INTEGER REFERENCES files (id) ON DELETE SET NULL,        -- the current picture
    clean_file_id INTEGER REFERENCES files (id) ON DELETE SET NULL,  -- picture without our text (module 06)
    source TEXT NOT NULL DEFAULT 'generated', -- generated | upload | library | avatar | video_frame | editor
    source_ref_json TEXT,                     -- where a picked picture came from
    prompt_text TEXT,                         -- exactly what went to the model last time
    attachments_json TEXT,                    -- [{role, label, file_id, mime}] of the last request
    text_blocks_json TEXT NOT NULL DEFAULT '[]',  -- words for the picture: [{role: headline|body|accent, text}]
    text_layers_json TEXT NOT NULL DEFAULT '[]',  -- module 06
    text_zones_json TEXT,                     -- module 06
    objects_json TEXT,                        -- {sha, items: [{id, label, box}], model_id, cost_usd, at}
    objects_sha TEXT,                         -- sha256 of the picture the objects were found on
    versions_json TEXT NOT NULL DEFAULT '[]', -- [{file_id, at, mode, prompt_text, source, cost_usd, call_ids, model_id}]
    job_id INTEGER,
    error_code TEXT,
    error_text TEXT,                          -- Google's words, verbatim
    drawing_since TEXT,
    cost_usd REAL NOT NULL DEFAULT 0,         -- everything spent on this frame
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_frames_work ON frames (work_id, position);
CREATE INDEX idx_frames_file ON frames (file_id);
CREATE INDEX idx_frames_clean_file ON frames (clean_file_id);
CREATE INDEX idx_frames_status ON frames (status);
