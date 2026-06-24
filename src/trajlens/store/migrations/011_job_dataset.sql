-- Jobs gain a dataset_id so the UI can recover run status after a tab/browser
-- close (sessionStorage held the only job_ids before). Nullable: old rows and
-- dataset-less runs (e.g. "run over all") stay NULL.
ALTER TABLE jobs ADD COLUMN dataset_id TEXT;
CREATE INDEX IF NOT EXISTS idx_jobs_dataset ON jobs(dataset_id, created_at DESC);
