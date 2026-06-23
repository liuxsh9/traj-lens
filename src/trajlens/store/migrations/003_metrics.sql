CREATE TABLE IF NOT EXISTS metrics (
  content_hash TEXT NOT NULL REFERENCES trajectories(content_hash),
  metric_id    TEXT NOT NULL,
  value        TEXT NOT NULL,
  version      TEXT NOT NULL,
  produced_at  TEXT NOT NULL,
  PRIMARY KEY (content_hash, metric_id)
);
