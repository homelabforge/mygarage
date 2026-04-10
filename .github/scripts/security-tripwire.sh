#!/usr/bin/env bash
# Security tripwire: catches common auth bypass patterns.
# Primary regression protection is the non-owner 403 integration tests.
set -euo pipefail

FOUND=0
if grep -rPn 'select\(Vehicle\)\.where\(Vehicle\.vin' backend/app/routes/ | grep -v 'analytics.py' | grep -v 'vehicles.py' | grep -v 'dashboard.py' | grep -v 'quick_entry.py' | grep -v 'calendar.py'; then
  echo "ERROR: Found raw Vehicle existence checks in route files."
  echo "Use get_vehicle_or_403() instead. See: backend/app/services/auth.py"
  FOUND=1
fi
if grep -rPn 'def verify_vehicle_exists' backend/app/routes/; then
  echo "ERROR: Found verify_vehicle_exists helper in route files."
  echo "Use get_vehicle_or_403() instead."
  FOUND=1
fi
exit $FOUND
