-- Module 06: text on a picture and the canvas editor. A design is one opening of the
-- «Text on image» tool on a studio frame: the clean background, the words, the layers
-- placed over it. «Save» renders the layers with Pillow and puts the result into the
-- frame as a new version (source «editor»); the layers stay here and on the frame
-- (frames.text_layers_json), so the next opening shows them again.
-- chat_id / message_id point at chats (module 15) without a foreign key.

CREATE TABLE text_designs (
    id INTEGER PRIMARY KEY,
    frame_id INTEGER NOT NULL REFERENCES frames (id) ON DELETE CASCADE,
    chat_id INTEGER,                             -- chats.id the tool was opened from
    message_id INTEGER,                          -- chat_messages.id of the picture
    kit_id INTEGER,                              -- brand_kits.id whose fonts and colours the editor offers
    background_file_id INTEGER REFERENCES files (id) ON DELETE SET NULL,  -- the picture without our text
    width INTEGER NOT NULL DEFAULT 0,            -- the background in pixels
    height INTEGER NOT NULL DEFAULT 0,
    texts_json TEXT NOT NULL DEFAULT '[]',       -- [{id, role: headline|body|accent, text, size: sm|md|lg|xl}]
    layers_json TEXT NOT NULL DEFAULT '[]',      -- canvas layers, boxes in fractions of the picture
    options_json TEXT NOT NULL DEFAULT '{}',     -- {language, ...} what the panels last used
    placement_json TEXT,                         -- the last answer of «Place the text» {blocks, source, model_id, at}
    result_file_id INTEGER REFERENCES files (id) ON DELETE SET NULL,      -- the last saved picture
    status TEXT NOT NULL DEFAULT 'draft',        -- draft | saved
    cost_usd REAL NOT NULL DEFAULT 0,            -- everything the tool spent on this design (journal)
    saved_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_text_designs_frame ON text_designs (frame_id, id);
CREATE INDEX idx_text_designs_background ON text_designs (background_file_id);

-- Every «Save»: which picture it made and the layers it was made from, so opening the
-- tool on an older saved picture of the chat brings back exactly those layers.
CREATE TABLE text_saves (
    id INTEGER PRIMARY KEY,
    design_id INTEGER NOT NULL REFERENCES text_designs (id) ON DELETE CASCADE,
    frame_id INTEGER NOT NULL,
    file_id INTEGER REFERENCES files (id) ON DELETE SET NULL,             -- the saved picture
    background_file_id INTEGER REFERENCES files (id) ON DELETE SET NULL,
    texts_json TEXT NOT NULL DEFAULT '[]',
    layers_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
CREATE INDEX idx_text_saves_file ON text_saves (file_id);
CREATE INDEX idx_text_saves_design ON text_saves (design_id, id);

-- «Generate» tab: each press asks the image model for 1–4 new backgrounds (one job).
CREATE TABLE text_backgrounds (
    id INTEGER PRIMARY KEY,
    design_id INTEGER NOT NULL REFERENCES text_designs (id) ON DELETE CASCADE,
    job_id INTEGER,
    n INTEGER NOT NULL DEFAULT 0,                -- the place of the variant in its press (0..3)
    prompt TEXT NOT NULL DEFAULT '',             -- exactly what was sent
    use_current INTEGER NOT NULL DEFAULT 0,      -- 1 = the current background went along as a picture
    status TEXT NOT NULL DEFAULT 'queued',       -- queued | running | done | error | cancelled
    file_id INTEGER REFERENCES files (id) ON DELETE SET NULL,
    model_id TEXT,
    cost_usd REAL NOT NULL DEFAULT 0,
    error_code TEXT,
    error TEXT,                                  -- Google's words verbatim
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_text_backgrounds_design ON text_backgrounds (design_id, id);
CREATE INDEX idx_text_backgrounds_job ON text_backgrounds (job_id);

-- Ready layouts of the editor: a set of layers dropped onto the picture in one press.
-- Built-in rows have a code (their title comes from the locale text.layouts.<code>);
-- the person's own rows have a title and no code.
CREATE TABLE editor_layouts (
    id INTEGER PRIMARY KEY,
    code TEXT UNIQUE,
    title TEXT NOT NULL DEFAULT '',
    layers_json TEXT NOT NULL DEFAULT '[]',
    builtin INTEGER NOT NULL DEFAULT 0,
    sort INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- The brand's type specimen for «the model draws the letters», one per font set.
CREATE TABLE text_font_sheets (
    id INTEGER PRIMARY KEY,
    signature TEXT NOT NULL UNIQUE,              -- sha1 of the font list (12 hex characters)
    kit_id INTEGER,
    file_id INTEGER REFERENCES files (id) ON DELETE CASCADE,
    fonts INTEGER NOT NULL DEFAULT 0,            -- faces drawn on the sheet
    created_at TEXT NOT NULL
);

INSERT INTO editor_layouts (code, title, layers_json, builtin, sort, created_at, updated_at) VALUES
('bottom_caption', '', '[
  {"type":"text","role":"headline","x":0.07,"y":0.68,"w":0.86,"h":0.14,"size":"xl","align":"left","vertical":"bottom","bold":true,"color":"#FFFFFF","scrim":false,"shadow":true},
  {"type":"text","role":"body","x":0.07,"y":0.83,"w":0.86,"h":0.10,"size":"md","align":"left","vertical":"top","bold":false,"color":"#FFFFFF","scrim":false,"shadow":true}
]', 1, 10, '2026-10-16T00:00:00.000Z', '2026-10-16T00:00:00.000Z'),
('top_title', '', '[
  {"type":"text","role":"headline","x":0.08,"y":0.06,"w":0.84,"h":0.16,"size":"xl","align":"center","vertical":"top","bold":true,"color":"#FFFFFF","scrim":true,"shadow":false},
  {"type":"logo","x":0.80,"y":0.88,"w":0.14,"h":0.08,"opacity":1}
]', 1, 20, '2026-10-16T00:00:00.000Z', '2026-10-16T00:00:00.000Z'),
('center_card', '', '[
  {"type":"shape","shape":"rect","x":0.12,"y":0.30,"w":0.76,"h":0.40,"fill":"#FFFFFF","opacity":0.88,"radius":0.03},
  {"type":"text","role":"headline","x":0.17,"y":0.34,"w":0.66,"h":0.17,"size":"lg","align":"center","vertical":"middle","bold":true,"color":"#111111","scrim":false,"shadow":false},
  {"type":"text","role":"body","x":0.17,"y":0.52,"w":0.66,"h":0.14,"size":"md","align":"center","vertical":"top","bold":false,"color":"#333333","scrim":false,"shadow":false}
]', 1, 30, '2026-10-16T00:00:00.000Z', '2026-10-16T00:00:00.000Z'),
('bottom_band', '', '[
  {"type":"shape","shape":"rect","x":0,"y":0.80,"w":1,"h":0.20,"fill":"#111111","opacity":0.82,"radius":0},
  {"type":"text","role":"headline","x":0.06,"y":0.83,"w":0.60,"h":0.14,"size":"lg","align":"left","vertical":"middle","bold":true,"color":"#FFFFFF","scrim":false,"shadow":false},
  {"type":"text","role":"accent","x":0.68,"y":0.84,"w":0.26,"h":0.12,"size":"md","align":"right","vertical":"middle","bold":true,"color":"#FFD54A","scrim":false,"shadow":false}
]', 1, 40, '2026-10-16T00:00:00.000Z', '2026-10-16T00:00:00.000Z'),
('corner_badge', '', '[
  {"type":"shape","shape":"ellipse","x":0.70,"y":0.05,"w":0.25,"h":0.25,"fill":"#E53935","opacity":1,"radius":0},
  {"type":"text","role":"accent","x":0.72,"y":0.10,"w":0.21,"h":0.15,"size":"lg","align":"center","vertical":"middle","bold":true,"color":"#FFFFFF","scrim":false,"shadow":false},
  {"type":"text","role":"headline","x":0.07,"y":0.74,"w":0.80,"h":0.18,"size":"xl","align":"left","vertical":"bottom","bold":true,"color":"#FFFFFF","scrim":true,"shadow":false}
]', 1, 50, '2026-10-16T00:00:00.000Z', '2026-10-16T00:00:00.000Z');
