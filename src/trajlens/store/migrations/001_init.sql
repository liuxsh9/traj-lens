CREATE TABLE IF NOT EXISTS trajectories (
  content_hash TEXT PRIMARY KEY,
  items_count  INTEGER NOT NULL,
  tools        TEXT NOT NULL DEFAULT '[]',
  meta         TEXT NOT NULL DEFAULT '{}',
  created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ingestions (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  content_hash TEXT NOT NULL REFERENCES trajectories(content_hash),
  source_path  TEXT,
  raw_sha      TEXT,
  ingested_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_blobs (
  raw_sha TEXT PRIMARY KEY,
  path    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS items (
  content_hash TEXT NOT NULL REFERENCES trajectories(content_hash),
  idx          INTEGER NOT NULL,
  type         TEXT NOT NULL,
  payload      TEXT NOT NULL,
  provenance   TEXT,
  PRIMARY KEY (content_hash, idx)
);
