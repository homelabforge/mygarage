#!/usr/bin/env bash
# Manual teardown for the e2e stack. Used when E2E_KEEP=1 left things up.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
docker compose -p mygarage-e2e -f "$HERE/compose.yml" down -v --remove-orphans
