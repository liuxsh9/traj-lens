-- Tombstone of deleted dataset ids. Dataset ids are name-derived (_slug) and
-- would otherwise be recycled on recreate, aliasing a new same-name dataset to
-- its deleted predecessor in caches, URLs, and dataset_id-keyed tables.
CREATE TABLE IF NOT EXISTS retired_dataset_ids (id TEXT PRIMARY KEY);
