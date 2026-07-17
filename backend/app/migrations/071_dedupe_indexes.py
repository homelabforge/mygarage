"""Drop redundant hand-named indexes that duplicate model-declared ones.

Each target index duplicates a model/create_all index on the same column(s) under
a different name (nothing dedupes differently-named indexes), so a fresh replay
carries both. Also drops the plain ix_users_oidc_subject/provider that create_all
built from the old bare column flags — the model now declares migration 011's
leaner partial indexes (idx_users_oidc_*), which are kept. Dialect-neutral
(DROP INDEX IF EXISTS), idempotent, forward-only, NON-FATAL.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, text

REDUNDANT_INDEXES = (
    "idx_csrf_token",  # dup of ix_csrf_tokens_token (mig 012)
    "idx_odometer_fuel_record_id",  # dup of ix_odometer_records_fuel_record_id (mig 055)
    "idx_users_auth_method",  # dup of ix_users_auth_method (mig 011)
    "ix_users_oidc_subject",  # old plain create_all index; model now uses partial idx_users_oidc_subject
    "ix_users_oidc_provider",  # old plain create_all index; model now uses partial idx_users_oidc_provider
)


def _get_fallback_engine():
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine=None) -> None:
    """Drop redundant indexes (DROP INDEX IF EXISTS is idempotent + guarded)."""
    if engine is None:
        engine = _get_fallback_engine()
    print("Migration 071: drop redundant duplicate indexes...")
    for idx in REDUNDANT_INDEXES:
        with engine.begin() as conn:
            conn.execute(text(f'DROP INDEX IF EXISTS "{idx}"'))
            print(f"  - dropped index {idx} (if it existed)")
    print("Migration 071 complete.")
    # NOTE (R1-H2): no broad try/except — a DROP INDEX error must raise (unstamped,
    # retryable). DROP INDEX IF EXISTS is inherently idempotent + a guarded no-op.


def downgrade() -> None:  # pragma: no cover
    raise NotImplementedError("Migration 071 is forward-only.")


if __name__ == "__main__":
    upgrade()
