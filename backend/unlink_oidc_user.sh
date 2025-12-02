#!/bin/bash
# Wrapper script to run unlink_oidc.py with correct Python path

cd /app/app
export PYTHONPATH=/app/app:$PYTHONPATH
python3 unlink_oidc.py "$@"
