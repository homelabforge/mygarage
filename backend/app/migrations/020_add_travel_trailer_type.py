"""Add TravelTrailer vehicle type.

This migration adds 'TravelTrailer' as a new vehicle type option.

Background:
- TravelTrailer is for bumper-pull recreational trailers with living quarters
- FifthWheel is for gooseneck recreational trailers with living quarters
- Trailer is for utility/cargo/boat/equipment trailers without RV features

TravelTrailers have the same features as FifthWheels:
- Propane tracking for appliances
- Spot rental tracking for RV parks
- No fuel/odometer tracking (non-motorized)

Created: 2025-12-27
"""

import os
from pathlib import Path

from sqlalchemy import create_engine


def _get_fallback_engine():
    """Build a SQLite engine from environment for standalone execution."""
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine=None):
    """Add TravelTrailer to vehicle_type validation."""
    if engine is None:
        engine = _get_fallback_engine()

    with engine.begin():
        # Note: SQLite doesn't support modifying CHECK constraints directly
        # The vehicle_type constraint is enforced at the application level
        # in backend/app/models/vehicle.py and backend/app/schemas/vehicle.py
        print("✓ TravelTrailer vehicle type validation updated in application layer")


if __name__ == "__main__":
    upgrade()
