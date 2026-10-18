#!/usr/bin/env bash
# repo_intel verify.sh — health checks against the running stack.
set -euo pipefail

red()   { printf '\033[0;31m%s\033[0m\n' "$1" >&2; }
green() { printf '\033[0;32m%s\033[0m\n' "$1" >&2; }
info()  { printf '\033[0;34m%s\033[0m\n' "$1" >&2; }

HOST=${REPO_INTEL_HOST:-127.0.0.1}
PORT=${REPO_INTEL_PORT:-8765}
BASE="http://${HOST}:${PORT}"

passed=0
failed=0

check() {
  local label="$1"
  if [ "$2" -eq 0 ]; then
    green "PASS  $label"
    passed=$((passed + 1))
  else
    red   "FAIL  $label"
    failed=$((failed + 1))
  fi
}

info "=== repo_intel verify ==="
info "Target: $BASE"

# --- live ---
HTTP=$(curl -sf -o /dev/null -w "%{http_code}" "${BASE}/health/live" 2>/dev/null || echo 000)
if [[ "$HTTP" == "200" ]]; then
  check "live endpoint" 0
else
  check "live endpoint (got HTTP $HTTP)" 1
fi

# --- ready ---
HTTP=$(curl -sf -o /dev/null -w "%{http_code}" "${BASE}/health/ready" 2>/dev/null || echo 000)
# 200 or 503 means the endpoint responds; 000 means unreachable
if [[ "$HTTP" == "200" ]]; then
  check "ready endpoint (all checks ok)" 0
elif [[ "$HTTP" == "503" ]]; then
  check "ready endpoint (some deps down)" 1
else
  check "ready endpoint (got HTTP $HTTP)" 1
fi

# --- containers ---
CNT=$(docker ps --filter "name=repo_intel" --filter "status=running" -q 2>/dev/null | wc -l)
if [[ "$CNT" -ge 2 ]]; then
  check "containers running ($CNT)" 0
else
  check "containers running ($CNT found, need >= 2)" 1
fi

# --- db persistence ---
VOL=$(docker volume ls --quiet 2>/dev/null | grep -c repo_intel_pgdata || true)
if [[ "$VOL" -ge 1 ]]; then
  check "Postgres volume exists" 0
else
  check "Postgres volume missing" 1
fi

echo ""
info "Total: $passed passed, $failed failed"
[[ "$failed" -eq 0 ]] && green "All verifications ok." || red "Some checks failed."
exit "$failed"
