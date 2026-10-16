-- Module 12: clip editor. A project is a source video plus a list of edits.
-- the source file is never changed, every export is a new file.

CREATE TABLE clip_projects (
    id INTEGER PRIMARY KEY,
    -- the source video. The usage provider keeps it from being deleted while a project uses it
    file_id INTEGER NOT NULL REFERENCES files (id) ON DELETE CASCADE,
    title TEXT NOT NULL DEFAULT '',
    state_json TEXT NOT NULL DEFAULT '{}',    -- edits: trim, cuts, removed, crop, layers, subtitles, audio
    source_json TEXT NOT NULL DEFAULT '{}',   -- {duration, width, height} of the source at open time
    brand_json TEXT,                          -- brand kit snapshot (brand.snapshot_kit) or NULL
    preview_file_id INTEGER REFERENCES files (id) ON DELETE SET NULL,  -- last preview (service file)
    status TEXT NOT NULL DEFAULT 'draft',     -- draft | exported
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_clip_projects_file ON clip_projects (file_id, id);
CREATE INDEX idx_clip_projects_preview ON clip_projects (preview_file_id);

-- Finished exports: one row per file (an export "in parts" gives several rows).
CREATE TABLE video_exports (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES clip_projects (id) ON DELETE CASCADE,
    file_id INTEGER NOT NULL REFERENCES files (id) ON DELETE CASCADE,
    job_id INTEGER,
    part_index INTEGER NOT NULL DEFAULT 0,
    part_count INTEGER NOT NULL DEFAULT 1,
    width INTEGER,
    height INTEGER,
    duration REAL,
    params_json TEXT NOT NULL DEFAULT '{}',   -- what was exported: size, segments, layers, subtitles, tracks
    created_at TEXT NOT NULL
);
CREATE INDEX idx_video_exports_project ON video_exports (project_id, id);
CREATE INDEX idx_video_exports_file ON video_exports (file_id);

-- Subtitle looks. Sizes are fractions of the frame, colors are #RRGGBB.
CREATE TABLE subtitle_presets (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    mode TEXT NOT NULL DEFAULT 'line',        -- line | word
    font_family TEXT NOT NULL DEFAULT 'DejaVu Sans',
    font_size_ratio REAL NOT NULL DEFAULT 0.045,
    bold INTEGER NOT NULL DEFAULT 1,
    italic INTEGER NOT NULL DEFAULT 0,
    uppercase INTEGER NOT NULL DEFAULT 0,
    primary_color TEXT NOT NULL DEFAULT '#FFFFFF',
    highlight_color TEXT NOT NULL DEFAULT '#FFE066',
    outline_color TEXT NOT NULL DEFAULT '#000000',
    back_color TEXT NOT NULL DEFAULT '#000000',
    back_opacity REAL NOT NULL DEFAULT 0,
    outline_ratio REAL NOT NULL DEFAULT 0.08,
    shadow_ratio REAL NOT NULL DEFAULT 0.04,
    border_style INTEGER NOT NULL DEFAULT 1,  -- 1 outline | 3 box
    alignment INTEGER NOT NULL DEFAULT 2,     -- ASS numpad: 2 bottom, 5 middle, 8 top
    margin_v_ratio REAL NOT NULL DEFAULT 0.12,
    margin_h_ratio REAL NOT NULL DEFAULT 0.06,
    max_words_per_line INTEGER NOT NULL DEFAULT 4,
    use_brand INTEGER NOT NULL DEFAULT 0,     -- take highlight, outline and font from the brand kit
    sort INTEGER NOT NULL DEFAULT 0
);

INSERT INTO subtitle_presets (code, name, description, mode, font_family, font_size_ratio, bold, italic, uppercase,
    primary_color, highlight_color, outline_color, back_color, back_opacity, outline_ratio, shadow_ratio,
    border_style, alignment, margin_v_ratio, margin_h_ratio, max_words_per_line, use_brand, sort) VALUES
('clean', 'Clean', 'White text with a dark outline, the spoken word lit up.', 'line', 'DejaVu Sans', 0.045, 1, 0, 0,
    '#FFFFFF', '#FFE066', '#000000', '#000000', 0.0, 0.08, 0.04, 1, 2, 0.12, 0.06, 4, 0, 1),
('boxed', 'Boxed', 'Text on a dark box, easy to read over any picture.', 'line', 'DejaVu Sans', 0.042, 0, 0, 0,
    '#FFFFFF', '#FFE066', '#000000', '#000000', 0.65, 0.04, 0.0, 3, 2, 0.10, 0.07, 5, 0, 2),
('pop', 'Pop', 'One big word at a time in the middle of the frame.', 'word', 'DejaVu Sans', 0.075, 1, 0, 1,
    '#FFFFFF', '#FFD400', '#000000', '#000000', 0.0, 0.14, 0.06, 1, 5, 0.0, 0.08, 1, 0, 3),
('brand', 'Brand', 'Like Clean, with the brand kit color and font.', 'line', 'DejaVu Sans', 0.048, 1, 0, 0,
    '#FFFFFF', '#FFD400', '#000000', '#000000', 0.0, 0.09, 0.04, 1, 2, 0.12, 0.06, 4, 1, 4);

-- Speech recognized by the local stt service (free). Reused for the same file, model and language.
CREATE TABLE transcripts (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES files (id) ON DELETE CASCADE,
    engine TEXT NOT NULL DEFAULT 'faster-whisper',
    model TEXT NOT NULL,
    requested_language TEXT NOT NULL DEFAULT 'auto',  -- what was asked: auto | ru | uk | en
    language TEXT,                            -- what was found (ISO code)
    text TEXT NOT NULL DEFAULT '',
    words_json TEXT NOT NULL DEFAULT '[]',    -- [{"text", "start", "end"}] seconds of the source
    duration REAL,                            -- seconds of audio
    elapsed_s REAL,                           -- how long recognition took on this computer (model ready → text)
    job_id INTEGER,
    created_at TEXT NOT NULL
);
CREATE INDEX idx_transcripts_file ON transcripts (file_id, model, requested_language, id);
CREATE INDEX idx_transcripts_model ON transcripts (model, id);
