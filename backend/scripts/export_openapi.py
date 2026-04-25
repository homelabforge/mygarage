"""Export OpenAPI schema from FastAPI app for frontend type generation.

Usage: PYTHONPATH=. python3 scripts/export_openapi.py <output_path>

MyGarage-specific: Uses MYGARAGE_ env prefix and isolates all file I/O
to a temp directory to avoid touching /data/ or creating secret keys.
"""

import json
import logging
import os
import sys
import tempfile

# Suppress app startup logs (middleware, CORS, etc.) but preserve errors
logging.disable(logging.WARNING)

# MyGarage uses MYGARAGE_ prefix for all env vars (config.py:165).
# Settings() instantiation triggers get_or_create_secret_key() which
# writes to /data/secret.key — we must set MYGARAGE_SECRET_KEY to bypass
# the default_factory and prevent filesystem side effects.
_tmpdir = tempfile.TemporaryDirectory(prefix="mygarage-openapi-")
_tmp = _tmpdir.name

os.environ.setdefault("MYGARAGE_DATABASE_URL", f"sqlite+aiosqlite:///{_tmp}/openapi.db")
os.environ.setdefault("MYGARAGE_SECRET_KEY", "openapi-export-dummy-key")
os.environ.setdefault("MYGARAGE_DATA_DIR", _tmp)
os.environ.setdefault("MYGARAGE_ATTACHMENTS_DIR", os.path.join(_tmp, "attachments"))
os.environ.setdefault("MYGARAGE_PHOTOS_DIR", os.path.join(_tmp, "photos"))
os.environ.setdefault("MYGARAGE_DOCUMENTS_DIR", os.path.join(_tmp, "documents"))

try:
    from app.main import app

    schema = app.openapi()
except Exception as e:
    print(f"ERROR: Failed to generate OpenAPI schema: {e}", file=sys.stderr)
    sys.exit(1)
finally:
    _tmpdir.cleanup()

# Pin info.version to a constant so the committed openapi.json doesn't drift
# every time pyproject.toml is bumped. The real version is still served by the
# runtime FastAPI app (app.openapi() reads settings.app_version directly); this
# strip only affects the file fed into openapi-typescript, which doesn't use
# info.version. Without this, every release fails the api-types-freshness CI
# gate until someone remembers to regenerate.
schema.setdefault("info", {})["version"] = "0.0.0"

output = json.dumps(schema, indent=2, sort_keys=True) + "\n"

if len(sys.argv) < 2:
    print(output, end="")
    sys.exit(0)

output_path = os.path.abspath(sys.argv[1])
output_dir = os.path.dirname(output_path)

tmp_path: str | None = None
try:
    fd, tmp_path = tempfile.mkstemp(dir=output_dir, suffix=".json.tmp")
    with os.fdopen(fd, "w") as f:
        f.write(output)
    os.replace(tmp_path, output_path)
except Exception as e:
    if tmp_path is not None and os.path.exists(tmp_path):
        os.unlink(tmp_path)
    print(f"ERROR: Failed to write {output_path}: {e}", file=sys.stderr)
    sys.exit(1)
