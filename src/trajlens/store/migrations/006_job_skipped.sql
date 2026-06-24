-- Track cache-skipped targets so the UI can report "N already annotated"
-- instead of misreporting them as "done 0/total".
ALTER TABLE jobs ADD COLUMN skipped INTEGER NOT NULL DEFAULT 0;
