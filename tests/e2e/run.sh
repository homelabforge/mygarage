#!/usr/bin/env bash
# End-to-end release gate for MyGarage.
#
# Builds the production image from the current working tree, brings up a
# disposable PG + SQLite stack, and runs the smoke test against both. Always
# tears down on exit (success OR failure).
#
# Exit codes:
#   0  all checks passed
#   1  build, startup, or smoke check failed
#
# Usage:
#   bash tests/e2e/run.sh                 # full cycle
#   E2E_KEEP=1 bash tests/e2e/run.sh      # leave stack running on failure (debug)
#   E2E_NO_BUILD=1 bash tests/e2e/run.sh  # reuse existing mygarage:e2e image

set -euo pipefail

# Resolve repo root from this script's location so it works regardless of CWD.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
COMPOSE_FILE="$HERE/compose.yml"
PROJECT="mygarage-e2e"

dc() {
  docker compose -p "$PROJECT" -f "$COMPOSE_FILE" "$@"
}

teardown() {
  local rc=$?
  if [[ "${E2E_KEEP:-0}" == "1" && $rc -ne 0 ]]; then
    echo
    echo "[e2e] E2E_KEEP=1 set and run failed — leaving stack up for inspection:"
    echo "      docker compose -p $PROJECT -f $COMPOSE_FILE ps"
    echo "      docker compose -p $PROJECT -f $COMPOSE_FILE logs"
    echo "      bash $HERE/teardown.sh   # when done"
    exit $rc
  fi
  echo
  echo "[e2e] Tearing down..."
  dc down -v --remove-orphans >/dev/null 2>&1 || true
  exit $rc
}
trap teardown EXIT

echo "[e2e] Repo: $REPO_ROOT"
echo "[e2e] Project: $PROJECT"
echo

# Always start clean. A leftover stack from a prior failed run would make
# results non-reproducible (we'd be testing against an upgraded DB instead
# of a fresh install).
dc down -v --remove-orphans >/dev/null 2>&1 || true

if [[ "${E2E_NO_BUILD:-0}" != "1" ]]; then
  echo "[e2e] Building mygarage:e2e from $REPO_ROOT ..."
  docker build -t mygarage:e2e "$REPO_ROOT" >/dev/null
  echo "[e2e] Build OK"
fi

echo "[e2e] Bringing up Postgres + 2 mygarage instances..."
dc up -d pg app-pg app-sqlite

echo "[e2e] Waiting for both apps to report healthy (up to 90s)..."
deadline=$(( $(date +%s) + 90 ))
while true; do
  pg_state=$(docker inspect --format '{{.State.Health.Status}}' mygarage-e2e-app-pg 2>/dev/null || echo "unknown")
  sq_state=$(docker inspect --format '{{.State.Health.Status}}' mygarage-e2e-app-sqlite 2>/dev/null || echo "unknown")
  if [[ "$pg_state" == "healthy" && "$sq_state" == "healthy" ]]; then
    echo "[e2e] Both healthy."
    break
  fi
  if (( $(date +%s) > deadline )); then
    echo "[e2e] ✗ Timeout waiting for healthy. PG=$pg_state SQLite=$sq_state"
    echo "[e2e] --- app-pg logs (tail) ---"
    docker logs --tail 50 mygarage-e2e-app-pg 2>&1 || true
    echo "[e2e] --- app-sqlite logs (tail) ---"
    docker logs --tail 50 mygarage-e2e-app-sqlite 2>&1 || true
    exit 1
  fi
  sleep 2
done

# Migration sanity — both DBs should report all 53 migrations applied. If
# the runner failed mid-stream (the #038/#048 class of bug), max() will be
# lower than the file count.
expected=$(ls "$REPO_ROOT/backend/app/migrations/"[0-9]*.py 2>/dev/null | wc -l)
echo "[e2e] Expecting $expected migrations applied on each DB."

pg_count=$(docker exec mygarage-e2e-pg psql -U mygarage -d mygarage -tAc "SELECT COUNT(*) FROM schema_migrations" 2>/dev/null || echo "0")
sqlite_count=$(docker exec mygarage-e2e-app-sqlite sh -c "python -c \"import sqlite3; print(sqlite3.connect('/data/mygarage.db').execute('SELECT COUNT(*) FROM schema_migrations').fetchone()[0])\"" 2>/dev/null || echo "0")
echo "[e2e]   PG: $pg_count applied"
echo "[e2e]   SQLite: $sqlite_count applied"

if [[ "$pg_count" != "$expected" ]]; then
  echo "[e2e] ✗ PG migration count $pg_count != expected $expected"
  echo "[e2e] --- app-pg logs (tail) ---"
  docker logs --tail 80 mygarage-e2e-app-pg 2>&1 | grep -iE "migration|error|fail" || true
  exit 1
fi
if [[ "$sqlite_count" != "$expected" ]]; then
  echo "[e2e] ✗ SQLite migration count $sqlite_count != expected $expected"
  echo "[e2e] --- app-sqlite logs (tail) ---"
  docker logs --tail 80 mygarage-e2e-app-sqlite 2>&1 | grep -iE "migration|error|fail" || true
  exit 1
fi
echo "[e2e] ✓ All migrations applied on both DBs."

echo
echo "[e2e] === Smoke against PG-backed app ==="
dc run --rm smoke http://app-pg:8686

echo
echo "[e2e] === Smoke against SQLite-backed app ==="
dc run --rm smoke http://app-sqlite:8686

echo
echo "[e2e] ✓ All checks passed."
