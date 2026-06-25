#!/usr/bin/env bash
# Idempotent upgrade/deploy for traj-lens. Run from anywhere; operates on the
# repo this script lives in. Guarantees the frontend bundle is rebuilt — the
# step humans forget, which serves stale JS against a newer API (see CLAUDE.md
# "Frontend build is NOT automatic").
#
# Usage:  ./scripts/deploy.sh [--no-pull]
set -euo pipefail

cd "$(dirname "$0")/.."
echo "▶ traj-lens deploy — $(pwd)"

# 1. Back up the DB before serve auto-migrates on next start.
DB="${TRAJLENS_DB:-trajlens.db}"
if [ -f "$DB" ] && command -v sqlite3 >/dev/null 2>&1; then
  bak="${DB%.db}-$(date +%F-%H%M%S).db"
  sqlite3 "$DB" ".backup '$bak'" && echo "✓ DB backed up → $bak"
fi

# 2. Sync source (skip with --no-pull, or when not a git checkout).
if [ "${1:-}" != "--no-pull" ] && [ -d .git ]; then
  git pull --ff-only && echo "✓ source updated"
fi

# 3. Python deps.
uv sync && echo "✓ python deps synced"

# 4. Frontend — ALWAYS rebuilt. This is the root-cause guard.
( cd web && npm ci && npm run build ) && echo "✓ frontend built"

# 5. Restart the service if systemd manages it, else hint.
if systemctl list-units --type=service 2>/dev/null | grep -q '\btrajlens\.service'; then
  sudo systemctl restart trajlens && echo "✓ trajlens restarted"
else
  echo "ℹ not under systemd — restart your serve process to pick up changes"
fi

echo "✔ deploy complete"
