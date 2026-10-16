-- Module 05: shot ideas. A set is one press of «Ideas» in the chat: the brief the person
-- filled, the setting they picked, the niche research and what the model wrote — a concept
-- and one prompt per frame. Drawing a card makes an ordinary studio work (module 04).
-- chat_id / message_id point at chats (module 15, created later) without a foreign key.

CREATE TABLE ideas_sets (
    id INTEGER PRIMARY KEY,
    chat_id INTEGER,                             -- chats.id, the chat the set was asked in
    message_id INTEGER,                          -- chat_messages.id of the set's card (kind ideas.concept)
    job_id INTEGER,                              -- jobs.id of «ideas.write»
    brief_json TEXT NOT NULL DEFAULT '{}',       -- the brief as sent: niche, brand, want, count, goal, ...
    files_json TEXT NOT NULL DEFAULT '[]',       -- [file_id, ...] every picture of the brief (media usages)
    scene_json TEXT NOT NULL DEFAULT '{}',       -- {axis: [item_id, ...]} the setting picked by hand
    research INTEGER NOT NULL DEFAULT 0,         -- 1 = the niche research was switched on
    research_json TEXT,                          -- {summary, sources, cached, created_at, error_code, error, ...}
    concept_json TEXT,                           -- {name, direction}
    images_json TEXT NOT NULL DEFAULT '[]',      -- [{n, title, prompt, edited, work_id, frame_id, drawn_at}]
    options_json TEXT NOT NULL DEFAULT '{}',     -- {draw_first, product_to_frames, image: {model_id, aspect, ...}}
    status TEXT NOT NULL DEFAULT 'running',      -- running | done | error | cancelled
    error_code TEXT,
    error TEXT,                                  -- Google's words verbatim when it refused
    cost_usd REAL NOT NULL DEFAULT 0,            -- research + ideas + rerolls (frames are counted by the studio)
    model_id TEXT,
    prompt_version INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_ideas_sets_chat ON ideas_sets (chat_id);

-- The niche research cache: one read per niche + platform, reused for ideas.research_cache_days.
CREATE TABLE ideas_research (
    id INTEGER PRIMARY KEY,
    niche_key TEXT NOT NULL,                     -- lower case, spaces collapsed
    platform_key TEXT NOT NULL DEFAULT '',
    niche TEXT NOT NULL DEFAULT '',
    platform TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL,
    sources_json TEXT NOT NULL DEFAULT '[]',     -- [{title, url}] the pages Google Search used
    model_id TEXT,
    cost_usd REAL,
    created_at TEXT NOT NULL,
    UNIQUE (niche_key, platform_key)
);
