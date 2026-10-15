-- Module 01: the connected Google key. Only safe facts live here;
-- the key itself is the file <data>/secrets/google-sa.json (mode 0600).
-- One row = the key that is connected now; replacing the key replaces the row.

CREATE TABLE google_credentials (
    id INTEGER PRIMARY KEY,
    project_id TEXT NOT NULL,
    client_email TEXT NOT NULL,
    private_key_id TEXT,
    uploaded_at TEXT NOT NULL,
    last_check_at TEXT,
    last_check_result_json TEXT      -- {"<check>": {"status": ..., "at": ..., "error": {...}}, ...}
);
