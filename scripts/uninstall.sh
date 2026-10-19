#!/usr/bin/env bash
# repo_intel uninstall.sh — tear down the Docker stack and clean up.
# Usage: ./scripts/uninstall.sh [--keep-data] [--dry-run]
set -euo pipefail

KEEP_DATA=false
DRY_RUN=false

for arg in "$@"; do
  case "$arg" in
    --keep-data) KEEP_DATA=true ;;
    --dry-run) DRY_RUN=true ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# ---------- helpers ----------
red()   { printf '\033[0;31m%s\033[0m\n' "$1" >&2; }
green() { printf '\033[0;32m%s\033[0m\n' "$1" >&2; }
info()  { printf '\033[0;34m%s\033[0m\n' "$1" >&2; }
die()   { red "ERROR: $*"; exit 1; }

# ---------- confirmation ----------
read -r -p "This will stop and remove all repo_intel containers. Continue? [y/N] " reply
case "$reply" in
  [yY][eE][sS]|[yY]) ;;
  *) echo "Aborted."; exit 0 ;;
esac

if [[ "$DRY_RUN" == "true" ]]; then
  info "[dry-run] would stop and remove containers"
  if [[ "$KEEP_DATA" != "true" ]]; then
    info "[dry-run] would remove PostgreSQL volume pgdata"
  fi
  info "Dry run complete."
  exit 0
fi

cd "$PROJECT_DIR"

info "Stopping and removing containers..."
docker compose down --remove-orphans

if [[ "$KEEP_DATA" != "true" ]]; then
  info "Removing PostgreSQL data volume..."
  docker compose down -v
  green "Volume removed (data destroyed)."
else
  info "Keeping PostgreSQL data volume."
fi

green "=== uninstall complete ==="
