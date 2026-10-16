-- Module 15: chat. A chat is a feed of requests and results. It is a wrapper:
-- pictures stay in studio works/frames and videos in video runs; a message only
-- points at them (chat_result_refs) and keeps what was sent.

CREATE TABLE chats (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    title_auto INTEGER NOT NULL DEFAULT 1,       -- 1 = taken from the first request; 0 = renamed by hand
    kind TEXT NOT NULL DEFAULT 'normal',         -- normal | avatar (module 09)
    kit_id INTEGER REFERENCES brand_kits (id) ON DELETE SET NULL,
    mode TEXT NOT NULL DEFAULT 'image',          -- last mode of the composer: image | video
    image_settings_json TEXT NOT NULL DEFAULT '{}',
    video_settings_json TEXT NOT NULL DEFAULT '{}',
    draft_json TEXT NOT NULL DEFAULT '{}',       -- {text, attachments: [{file_id, role}], reply_to, enhance, video_run_id}
    meta_json TEXT NOT NULL DEFAULT '{}',        -- extension data of other modules (avatar id…)
    archived_at TEXT,
    last_message_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_chats_recent ON chats (archived_at, last_message_at, id);

CREATE TABLE chat_messages (
    id INTEGER PRIMARY KEY,
    chat_id INTEGER NOT NULL REFERENCES chats (id) ON DELETE CASCADE,
    position INTEGER NOT NULL,                   -- order in the feed
    type TEXT NOT NULL,                          -- request | result | service
    kind TEXT NOT NULL DEFAULT 'text',           -- image | video | text | kinds of other modules (ideas…)
    mode TEXT,                                   -- image | video (requests and results)
    text TEXT NOT NULL DEFAULT '',               -- request: what the person wrote
    attachments_json TEXT NOT NULL DEFAULT '[]', -- [{file_id, role}]
    settings_json TEXT NOT NULL DEFAULT '{}',    -- request: snapshot of everything that went to the model
    reply_to INTEGER REFERENCES chat_messages (id) ON DELETE SET NULL,
    request_id INTEGER REFERENCES chat_messages (id) ON DELETE SET NULL,  -- result: its request
    refs_json TEXT NOT NULL DEFAULT '{}',        -- result: {work_id, run_id}
    data_json TEXT NOT NULL DEFAULT '{}',        -- result: {items: [...]} kept up to date from frames/clips
    status TEXT NOT NULL DEFAULT 'done',         -- enhancing | running | done | error | cancelled
    cost_usd REAL NOT NULL DEFAULT 0,
    error_code TEXT,
    error TEXT,                                  -- Google's answer verbatim when it came from Google
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_chat_messages_chat ON chat_messages (chat_id, position);
CREATE INDEX idx_chat_messages_status ON chat_messages (status);

-- What a result message shows: frames, works, video runs (later avatars).
-- Links /chat?frame=…, ?work=…, ?video=… are found through this table.
CREATE TABLE chat_result_refs (
    message_id INTEGER NOT NULL REFERENCES chat_messages (id) ON DELETE CASCADE,
    chat_id INTEGER NOT NULL REFERENCES chats (id) ON DELETE CASCADE,
    ref_type TEXT NOT NULL,                      -- frame | work | video_run | video_clip | avatar
    ref_id INTEGER NOT NULL,
    PRIMARY KEY (message_id, ref_type, ref_id)
);
CREATE INDEX idx_chat_result_refs_ref ON chat_result_refs (ref_type, ref_id);
