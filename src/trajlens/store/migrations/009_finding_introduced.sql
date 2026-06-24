-- Diff-baseline scanning (slice-5): attribute each finding to agent-introduced
-- vs pre-existing. introduced=1 means the finding's (item, rule) appeared in the
-- post-edit content but not the pre-edit content. introduced_count on the scan
-- row is the metric we actually care about (noise from inherited issues removed).
ALTER TABLE security_findings ADD COLUMN introduced INTEGER NOT NULL DEFAULT 1;
ALTER TABLE security_scans ADD COLUMN introduced_count INTEGER NOT NULL DEFAULT 0;
