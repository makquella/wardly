-- Shared cache of OpenDota reference data (docs/DATA_PLAN.md, stage 3).
-- The bodies are in R2 under opendota/ (stored as OpenDota sent them); this
-- table is only the refresh queue: what to fetch, when it last succeeded and
-- when it last failed. It holds public reference data and nothing about
-- players. heroStats and constants/items are seeded by the first cron run; a
-- successful heroStats adds the three per-hero rows for every hero it lists.
CREATE TABLE IF NOT EXISTS opendota_cache (
  key TEXT PRIMARY KEY,                  -- R2 key, "opendota/heroes/1/matchups.json"
  path TEXT NOT NULL,                    -- OpenDota path with its query, "/heroes/1/matchups"
  fetched_at INTEGER NOT NULL DEFAULT 0, -- ms since epoch of the last stored body; 0 = never
  size INTEGER,
  failed_at INTEGER,                     -- ms of the last failed refresh (backoff)
  fails INTEGER NOT NULL DEFAULT 0       -- failures in a row
);
CREATE INDEX IF NOT EXISTS opendota_cache_fetched ON opendota_cache (fetched_at);
