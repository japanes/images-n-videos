-- Module 07: style library — categories, built-in styles (from app/seeds/library) and own styles.

CREATE TABLE preset_categories (
    slug TEXT PRIMARY KEY,                    -- "obuv/krossovki"; the path is the identity
    parent TEXT,                              -- slug of the parent, NULL for a root
    depth INTEGER NOT NULL DEFAULT 0,
    sort INTEGER NOT NULL DEFAULT 0,
    title TEXT NOT NULL,                      -- as shipped (Russian in the factory export)
    title_uk TEXT,
    title_en TEXT,
    builtin INTEGER NOT NULL DEFAULT 1,       -- every category comes from the seed today
    removed_from_seed INTEGER NOT NULL DEFAULT 0,  -- gone from the seed, kept while own styles use it
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_preset_categories_parent ON preset_categories (parent, sort);

CREATE TABLE presets (
    id INTEGER PRIMARY KEY,
    code TEXT UNIQUE,                         -- built-ins: seed code ("style-14"); own styles: NULL
    kind TEXT NOT NULL DEFAULT 'style',       -- style | photo_style
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    prompt TEXT NOT NULL,                     -- may hold {{name}} / {{name|default}} slots
    text_zones_json TEXT,                     -- where lettering goes: {"canvas": {...}, "zones": [...]}
    category TEXT,                            -- preset_categories.slug (not enforced: a seed may drop it)
    is_builtin INTEGER NOT NULL DEFAULT 0,
    preview_seed TEXT,                        -- built-ins: path under app/seeds/library
    preview_file_id INTEGER REFERENCES files (id) ON DELETE SET NULL,  -- own styles
    copied_from TEXT,                         -- code of the built-in an own style was copied from
    removed_from_seed INTEGER NOT NULL DEFAULT 0,  -- built-in gone from the seed: hidden, kept for old works
    sort INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_presets_list ON presets (is_builtin, kind, removed_from_seed, sort);
CREATE INDEX idx_presets_category ON presets (category);
CREATE INDEX idx_presets_preview ON presets (preview_file_id);
