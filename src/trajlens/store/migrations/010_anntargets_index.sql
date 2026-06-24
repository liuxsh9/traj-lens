-- list-page CTE joins annotation_targets on content_hash, but the PK leads with
-- target_hash, so that join scanned the table. Index it for query_trajectories.
CREATE INDEX IF NOT EXISTS idx_anntargets_content ON annotation_targets(content_hash);
