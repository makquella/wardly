-- Match recordings sent by the player's consent (docs/DATA_PLAN.md, stage 5).
-- The anonymized gzip file is in R2 (r2_key, kept 60 days); this row only
-- indexes it. No match id, nickname, account id or installation id is stored:
-- the owner is the hash of the device key ("Delete my data" removes by it) and
-- install_hash is a salted hash used only for the hourly rate limit, so a row
-- cannot be joined to a profile or a share.
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,           -- "S-7F3KQ2", shown to the player
  created_at INTEGER NOT NULL,   -- ms since epoch
  owner_hash TEXT NOT NULL,      -- sha256 of the device key
  install_hash TEXT,             -- sha256("dac-session:" + install id), not joinable
  version TEXT,
  hero TEXT,
  minutes INTEGER,
  size INTEGER,
  r2_key TEXT NOT NULL,
  split TEXT NOT NULL            -- 'tune' or 'holdout', fixed by the id
);
CREATE INDEX IF NOT EXISTS sessions_created ON sessions (created_at);
CREATE INDEX IF NOT EXISTS sessions_owner ON sessions (owner_hash);
