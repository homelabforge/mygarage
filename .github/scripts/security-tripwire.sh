#!/usr/bin/env bash
# Security tripwire: catches vehicle-authorization bypass patterns.
#
# As of v2.28.0 this delegates to an AST checker (tools/authz_tripwire.py,
# stdlib-only, py3.11+) that inspects call arguments, decorators, the service
# layer, and a one-level call graph -- things the previous two greps could not
# see, which is why the v2.27.2 authorization cluster shipped undetected.
#
# Rollout: landed in --mode warn (surfaces the full finding set without gating)
# while Groups A-E are fixed, then flipped to --mode fail for enforcement. The
# CI gate name is unchanged so shared-workflows keeps invoking this script.
#
# Primary regression protection remains the non-owner 403 integration tests; the
# tripwire is the structural backstop.
set -euo pipefail

# Resolve the repo root from this script's location so it works regardless of
# the caller's CWD (CI invokes it from the repo root; bin/ci-check too).
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

# Rollout switch: "warn" prints findings but exits 0; "fail" gates CI.
# Flipped to "fail" in Phase 4: Groups A-E are fixed and the checker reports
# zero findings on the tree.
MODE="fail"

python3 backend/tools/authz_tripwire.py --mode "$MODE"
