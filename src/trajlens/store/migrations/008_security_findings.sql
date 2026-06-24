-- Persisted Semgrep findings (slice-5). Scanning is slow + external, so cache
-- it: findings rows + a per-trajectory scan-state row for staleness (ruleset
-- version) and to distinguish "scanned, 0 findings" from "never scanned".
CREATE TABLE IF NOT EXISTS security_findings (
  content_hash TEXT NOT NULL,
  item_idx     INTEGER NOT NULL,
  check_id     TEXT NOT NULL,
  severity     TEXT NOT NULL,
  message      TEXT NOT NULL,
  line         INTEGER
);
CREATE INDEX IF NOT EXISTS idx_secfind_hash ON security_findings(content_hash);

CREATE TABLE IF NOT EXISTS security_scans (
  content_hash    TEXT PRIMARY KEY,
  ruleset_version TEXT NOT NULL,
  scanned         INTEGER NOT NULL,  -- fragments fed to semgrep
  finding_count   INTEGER NOT NULL,
  scanned_at      TEXT NOT NULL
);
