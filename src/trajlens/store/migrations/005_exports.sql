CREATE TABLE IF NOT EXISTS export_artifacts (
    id          TEXT PRIMARY KEY,
    dataset_id  TEXT NOT NULL REFERENCES datasets(id),
    exporter    TEXT NOT NULL,
    config      TEXT NOT NULL DEFAULT '{}',
    traj_count  INTEGER NOT NULL DEFAULT 0,
    output_path TEXT,
    created_at  TEXT NOT NULL
);
