CREATE TABLE IF NOT EXISTS datasets (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS batches (
    id          TEXT PRIMARY KEY,
    dataset_id  TEXT NOT NULL REFERENCES datasets(id),
    name        TEXT NOT NULL DEFAULT '',
    format      TEXT NOT NULL,
    source_info TEXT NOT NULL DEFAULT '{}',
    traj_count  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);

ALTER TABLE ingestions ADD COLUMN batch_id TEXT;

-- Seed default dataset for backward compat
INSERT INTO datasets(id, name, description, created_at)
VALUES('_default', '_default', 'Auto-created default dataset', datetime('now'));

CREATE INDEX IF NOT EXISTS idx_ingestions_batch ON ingestions(batch_id);
CREATE INDEX IF NOT EXISTS idx_batches_dataset ON batches(dataset_id);
