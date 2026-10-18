#!/usr/bin/env bash
# repo_intel backup.sh — dump the PostgreSQL database.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKUP_DIR="${1:-$PROJECT_DIR/backups}"

mkdir -p "$BACKUP_DIR"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
FILE="$BACKUP_DIR/repo_intel_db_$TIMESTAMP.sql.gz"

echo "Backing up repo_intel database to $FILE"
docker compose -f "$PROJECT_DIR/compose.yaml" exec -T postgres \
  pg_dump -U repo_intel repo_intel | gzip > "$FILE"
echo "Done."
