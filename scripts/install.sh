#!/usr/bin/env bash
# repo_intel install.sh — bootstrap the Docker stack and run diagnostics.
# Usage: ./scripts/install.sh [--dry-run]
set -euo pipefail

DRY_RUN=false
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
  esac
done

# ---------- helpers ----------
red()   { printf '\033[0;31m%s\033[0m\n' "$1" >&2; }
green() { printf '\033[0;32m%s\033[0m\n' "$1" >&2; }
info()  { printf '\033[0;34m%s\033[0m\n' "$1" >&2; }
die()   { red "ERROR: $*"; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# ---------- preflight ----------
info "=== repo_intel install (dry_run=$DRY_RUN) ==="

preflight_checks=(
  "docker:Docker"
  "docker compose:docker compose plugin"
)

for spec in "${preflight_checks[@]}"; do
  cmd="${spec%%:*}"
  label="${spec##*:}"
  if ! command -v "$cmd" &>/dev/null && ! docker help "$cmd" &>/dev/null 2>&1; then
    # Some shells have docker-compose as a separate binary
    if [[ "$cmd" == "docker compose" ]]; then
      if docker compose version &>/dev/null; then
        continue
      fi
    fi
    die "$label is required but not found."
  fi
done
green "Preflight: Docker available"

# ---------- .env ----------
if [[ -f "$PROJECT_DIR/.env" ]]; then
  info ".env already exists — keeping it."
else
  if [[ -f "$PROJECT_DIR/.env.example" ]]; then
    cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
    # Generate a random DB password
    RAND_PASS=$(openssl rand -base64 20 2>/dev/null || head /dev/urandom | tr -dc A-Za-z0-9 | head -c 20)
    sed -i.bak "s/CHANGE_ME/$RAND_PASS/" "$PROJECT_DIR/.env"
    rm -f "$PROJECT_DIR/.env.bak"
    chmod 600 "$PROJECT_DIR/.env"
    green ".env created with random DB password"
  else
    die ".env.example not found."
  fi
fi

# ---------- docker compose ----------
if [[ "$DRY_RUN" == "true" ]]; then
  info "[dry-run] would run: docker compose -f $PROJECT_DIR/compose.yaml up -d --build"
  info "[dry-run] would run: alembic upgrade head"
  info "[dry-run] would run: repo-intel doctor"
  info "Dry run complete."
  exit 0
fi

cd "$PROJECT_DIR"

info "Building and starting containers..."
docker compose up -d --build

info "Waiting for services to become healthy..."
sleep 5
if ! docker compose ps --status=running --format json 2>/dev/null | grep -q repo_intel; then
  warn="Some services may not be running. Check: docker compose logs"
  red "$warn"
fi

# ---------- alembic ----------
info "Running alembic migrations..."
docker compose exec -T api alembic upgrade head || warn_exit="true"

if [[ "${warn_exit:-}" == "true" ]]; then
  red "Migration failed — check above output."
  exit 1
fi
green "Migrations applied."

# ---------- doctor ----------
info "Running diagnostics..."
docker compose exec -T api repo-intel doctor
DOCTOR_EXIT=$?

if [[ $DOCTOR_EXIT -ne 0 ]]; then
  red "Some doctor checks failed. Review the report above."
  exit 1
fi

# ---------- MCP connectivity ----------
info "Testing MCP endpoint connectivity..."
MCP_OK=false
MCP_DETAIL="N/A"
for attempt in 1 2 3; do
  if docker compose exec -T api curl -sf http://127.0.0.1:8765/mcp 2>/dev/null | grep -q "repo_intel"; then
    MCP_OK=true
    MCP_DETAIL="ok"
    break
  fi
  sleep 2
done

if [[ "$MCP_OK" != "true" ]]; then
  red "MCP endpoint not responding — check API container logs."
  exit 1
fi
green "MCP endpoint reachable"

# ---------- summary ----------
green "=== install complete ==="
info "Next steps:"
info "  1. Register a repo:  docker compose exec api repo-intel repo add /workspace"
info "  2. Index it:        docker compose exec api repo-intel index"
info "  3. Check status:    docker compose exec api repo-intel status"
info ""
info "Backup:   ./scripts/backup.sh"
info "Restore:  ./scripts/restore.sh <backup.sql.gz>"
info "Uninstall: ./scripts/uninstall.sh [--keep-data]"
