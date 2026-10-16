-- Module 09: avatars — one invented or photographed person, a written identity,
-- a chosen face and a pack of 36 shots drawn against it.

CREATE TABLE avatars (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    brief TEXT NOT NULL DEFAULT '',             -- the author's own words (description mode)
    init_mode TEXT NOT NULL DEFAULT 'reference',  -- reference | description | auto
    identity TEXT NOT NULL DEFAULT '',          -- the master identity, English
    identity_source TEXT NOT NULL DEFAULT '',   -- '' | model | manual
    identity_locked INTEGER NOT NULL DEFAULT 0, -- 1 after a face is chosen (or locked by hand)
    face_file_id INTEGER REFERENCES files (id) ON DELETE SET NULL,  -- the current face (= SHOT_01)
    image_model_id TEXT,                        -- NULL = the default image model
    candidate_count INTEGER NOT NULL DEFAULT 4, -- face candidates per request, 1..6
    as_subject INTEGER NOT NULL DEFAULT 1,      -- offered as a "person" subject (studio, @name)
    subject_id INTEGER,                         -- the mirrored brand subject (module 08)
    chat_id INTEGER,                            -- the avatar chat
    message_id INTEGER,                         -- the avatar card in that chat
    describe_job_id INTEGER,                    -- the running "Describe" job
    describe_message_id INTEGER,                -- the message that shows its result
    cost_usd REAL NOT NULL DEFAULT 0,           -- everything paid for this avatar (from the journal)
    archived_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_avatars_list ON avatars (archived_at, updated_at);

CREATE TABLE avatar_photos (
    id INTEGER PRIMARY KEY,
    avatar_id INTEGER NOT NULL REFERENCES avatars (id) ON DELETE CASCADE,
    kind TEXT NOT NULL,                         -- source | candidate | face | shot
    file_id INTEGER REFERENCES files (id) ON DELETE SET NULL,
    shot_code TEXT,                             -- shots: SHOT_01 … SHOT_36
    title TEXT NOT NULL DEFAULT '',
    angle TEXT NOT NULL DEFAULT '',             -- caption sent with the picture ("left profile")
    marked INTEGER NOT NULL DEFAULT 0,          -- source photos: sent with every shot
    sort INTEGER NOT NULL DEFAULT 0,
    custom_prompt TEXT,                         -- shots: the person's own wording of the shot
    prompt_text TEXT,                           -- what was sent the last time
    origin TEXT NOT NULL DEFAULT 'generated',   -- generated | upload | face
    message_id INTEGER,                         -- the chat message that shows this picture
    status TEXT NOT NULL DEFAULT 'empty',       -- empty | queued | drawing | done | error | archived
    job_id INTEGER,
    drawing_since TEXT,
    error_code TEXT,
    error_text TEXT,
    cost_usd REAL NOT NULL DEFAULT 0,
    meta_json TEXT NOT NULL DEFAULT '{}',       -- sizes asked and got, fit note, model, variation
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_avatar_photos_avatar ON avatar_photos (avatar_id, kind, sort);
CREATE INDEX idx_avatar_photos_file ON avatar_photos (file_id);
CREATE INDEX idx_avatar_photos_status ON avatar_photos (status);
