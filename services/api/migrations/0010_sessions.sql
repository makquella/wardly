-- Match recordings sent by the player's consent (docs/DATA_PLAN.md, stage 5).
-- The anonymized gzip file is in R2 (r2_key, kept 60 days); this row only
-- indexes it. No match id, nickname or account id is stored anywhere.
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,           -- "S-7F3KQ2", shown to the player
  created_at INTEGER NOT NULL,   -- ms since epoch
  install_id TEXT NOT NULL,
  owner_hash TEXT,               -- sha256 of the device key: "Delete my data" removes it
  version TEXT,
  hero TEXT,
  minutes INTEGER,
  size INTEGER,
  r2_key TEXT NOT NULL,
  split TEXT NOT NULL            -- 'tune' or 'holdout', fixed by the id
);
CREATE INDEX IF NOT EXISTS sessions_created ON sessions (created_at);
CREATE INDEX IF NOT EXISTS sessions_owner ON sessions (owner_hash);
CREATE INDEX IF NOT EXISTS sessions_install ON sessions (install_id);
