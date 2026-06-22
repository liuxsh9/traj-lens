CREATE TABLE IF NOT EXISTS annotators (
  id            TEXT NOT NULL,
  version       TEXT NOT NULL,
  config_hash   TEXT NOT NULL,
  active        INTEGER NOT NULL DEFAULT 1,
  registered_at TEXT NOT NULL,
  PRIMARY KEY (id, version)
);

CREATE TABLE IF NOT EXISTS annotations (
  target_hash       TEXT NOT NULL,
  annotator_id      TEXT NOT NULL,
  annotator_version TEXT NOT NULL,
  value             TEXT NOT NULL,
  inputs_hash       TEXT NOT NULL,
  produced_at       TEXT NOT NULL,
  PRIMARY KEY (target_hash, annotator_id, annotator_version)
);

-- maps target_hash back to trajectory for efficient per-trajectory annotation queries
CREATE TABLE IF NOT EXISTS annotation_targets (
  target_hash  TEXT NOT NULL,
  content_hash TEXT NOT NULL REFERENCES trajectories(content_hash),
  target_type  TEXT NOT NULL,
  target_idx   INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (target_hash, content_hash)
);

CREATE TABLE IF NOT EXISTS jobs (
  id           TEXT PRIMARY KEY,
  annotator_id TEXT NOT NULL,
  status       TEXT NOT NULL DEFAULT 'pending',
  total        INTEGER NOT NULL DEFAULT 0,
  done         INTEGER NOT NULL DEFAULT 0,
  errors       TEXT NOT NULL DEFAULT '[]',
  created_at   TEXT NOT NULL,
  updated_at   TEXT NOT NULL
);
