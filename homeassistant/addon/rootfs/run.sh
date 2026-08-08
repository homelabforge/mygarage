#!/usr/bin/env bash
set -euo pipefail

OPTIONS_FILE="/data/options.json"

if [[ -f "${OPTIONS_FILE}" ]]; then
  LOG_LEVEL=$(jq -r '.log_level // "info"' "${OPTIONS_FILE}")
  AUTH_MODE=$(jq -r '.auth_mode // "none"' "${OPTIONS_FILE}")
  TIMEZONE=$(jq -r '.timezone // "UTC"' "${OPTIONS_FILE}")
  SCHEDULER=$(jq -r '.scheduler_enabled // true' "${OPTIONS_FILE}")
else
  LOG_LEVEL="info"
  AUTH_MODE="none"
  TIMEZONE="UTC"
  SCHEDULER="true"
fi

export TZ="${TIMEZONE}"
export MYGARAGE_LOG_LEVEL="${LOG_LEVEL}"
export AUTH_MODE="${AUTH_MODE}"
export SCHEDULER_ENABLED="${SCHEDULER}"
export DATA_DIR="${DATA_DIR:-/data}"

mkdir -p /data/attachments /data/photos

# Supervisor add-on process stays as root; the published image defaults to
# UID 1000 which cannot write Supervisor's /data mount without chown.
exec granian \
  --interface asgi \
  --host 0.0.0.0 \
  --port 8686 \
  --workers 1 \
  app.main:app
