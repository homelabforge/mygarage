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


def upgrade():
    """Add TravelTrailer to vehicle_type validation."""
    # Get database path from environment
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    database_path = data_dir / "mygarage.db"
    database_url = f"sqlite:///{database_path}"

    # Create engine
    engine = create_engine(database_url)

    with engine.begin():
        # Note: SQLite doesn't support modifying CHECK constraints directly
        # The vehicle_type constraint is enforced at the application level
        # in backend/app/models/vehicle.py and backend/app/schemas/vehicle.py
        print("✓ TravelTrailer vehicle type validation updated in application layer")


if __name__ == "__main__":
    upgrade()
