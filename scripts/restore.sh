#!/usr/bin/env bash
# repo_intel restore.sh — restore the PostgreSQL database from a dump.
# Usage: ./scripts/restore.sh <backup.sql.gz> [--yes]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 &lt;backup.sql.gz&gt; [--yes]"
  exit 1
fi

BACKUP_FILE="$1"
YES=false
for arg in "$@"; do
  case "$arg" in
    --yes) YES=true ;;
  esac
done

if [[ ! -f "$BACKUP_FILE" ]]; then
  echo "ERROR: File not found: $BACKUP_FILE"
  exit 1
fi

if [[ "$YES" != "true" ]]; then
  read -r -p "This will overwrite the current database. Continue? [y/N] " reply
  case "$reply" in
    [yY][eE][sS]|[yY]) ;;
    *) echo "Aborted."; exit 0 ;;
  esac
fi

echo "Restoring from $BACKUP_FILE ..."
gunzip -c "$BACKUP_FILE" | docker compose -f "$PROJECT_DIR/compose.yaml" exec -T postgres \
  psql -U repo_intel repo_intel
echo "Restore complete."
