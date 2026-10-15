-- Module 08: brand kits (colors, tone, fonts, logos, references, brand elements) and subjects.

CREATE TABLE brand_kits (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    colors_json TEXT NOT NULL DEFAULT '[]',   -- [{"hex": "#1A2B3C", "label": "Main"}]
    tone TEXT NOT NULL DEFAULT '',            -- tone of voice for texts
    sort INTEGER NOT NULL DEFAULT 0,
    revision INTEGER NOT NULL DEFAULT 1,      -- +1 on any change of the kit or its assets
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE brand_assets (
    id INTEGER PRIMARY KEY,
    kit_id INTEGER NOT NULL REFERENCES brand_kits (id) ON DELETE CASCADE,
    -- font | reference | logo | frame | sticker | plate | badge | background | other
    -- (logo … other are the "brand elements")
    kind TEXT NOT NULL,
    file_id INTEGER REFERENCES files (id) ON DELETE CASCADE,  -- NULL only for a catalog font
    name TEXT NOT NULL DEFAULT '',
    position_hint TEXT NOT NULL DEFAULT '',   -- where to place it
    note TEXT NOT NULL DEFAULT '',            -- how to use it
    font_family TEXT,                         -- fonts: family name read from the file
    font_category TEXT,                       -- fonts: serif | sans | mono | display | handwriting
    font_source TEXT,                         -- fonts: upload | google
    google_family TEXT,                       -- fonts from the Google Fonts catalog (module 06)
    meta_json TEXT,                           -- fonts: weight, italic, style name
    sort INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX idx_brand_assets_kit ON brand_assets (kit_id, kind, sort);
CREATE INDEX idx_brand_assets_file ON brand_assets (file_id);

CREATE TABLE subjects (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'product',     -- product | person | prop
    description TEXT NOT NULL DEFAULT '',
    description_source TEXT NOT NULL DEFAULT 'manual',  -- manual | photo
    describe_focus TEXT NOT NULL DEFAULT '',  -- "what to describe" hint for describe-from-photos
    cover_file_id INTEGER REFERENCES files (id) ON DELETE SET NULL,  -- NULL = first photo
    one_off INTEGER NOT NULL DEFAULT 0,       -- quick subject made for one work, not in the library
    sort INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_subjects_list ON subjects (one_off, sort);

CREATE TABLE subject_photos (
    id INTEGER PRIMARY KEY,
    subject_id INTEGER NOT NULL REFERENCES subjects (id) ON DELETE CASCADE,
    file_id INTEGER NOT NULL REFERENCES files (id) ON DELETE CASCADE,
    angle TEXT NOT NULL DEFAULT '',           -- caption: "front", "back label" ...
    sort INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX idx_subject_photos_subject ON subject_photos (subject_id, sort);
CREATE INDEX idx_subject_photos_file ON subject_photos (file_id);
