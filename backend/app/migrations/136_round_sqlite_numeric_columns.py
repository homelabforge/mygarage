"""Round every Numeric column SQLite holds to its column's scale.

PG rounds a number to its column's scale on the way in; SQLite kept whatever it
was handed. Since 3.10 every write rounds first (`ScaledNumeric`), but rows
written before that still hold the raw value: an imperial odometer stored as
19867.35168 km never matches the 19867.35 a comparison binds, so the fuel
economy window and the widget's anchor tank miss it. This rounds them once.

Each float is rounded the way `ScaledNumeric` rounds a bind: through its repr,
half away from zero, and written back only when that changes it. Integers are
already at every scale, and a text or non-finite value is left as it is. One
too big to round is left too, the same as a bind.

The scales are hard-coded, a historical migration can't follow later models.
They're the scales after batch 7 widened its 14 columns, so a raw 1.31982 price
keeps four places. A table or column the database doesn't have is skipped.

Each table rounds in its own transaction. Not FATAL: a failure leaves what
3.10 does anyway (new writes round, old rows stay raw), the tables done so far
stay done, and the next boot picks up the rest. A no-op on PG.
"""

from __future__ import annotations

import logging
import os
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy import Connection, Engine, create_engine, inspect, text

FATAL = False

logger = logging.getLogger(__name__)

#: Rows read per round trip, so a big location_points table doesn't load at once.
BATCH = 5000

#: table -> {column: scale}, every model Numeric column after batch 7.
COLUMNS: dict[str, dict[str, int]] = {
    "address_book": {"latitude": 8, "longitude": 8, "rating": 2},
    "brake_axles": {
        "min_thickness_mm": 2,
        "new_thickness_mm": 2,
        "rotor_min_mm": 2,
        "drum_max_mm": 2,
    },
    "brake_jobs": {"odometer_km": 2, "engine_hours": 1},
    "brake_measurements": {
        "odometer_km": 2,
        "engine_hours": 1,
        "inner_pad_mm": 2,
        "outer_pad_mm": 2,
        "rotor_mm": 2,
        "shoe_mm": 2,
        "drum_mm": 2,
    },
    "def_records": {
        "odometer_km": 2,
        "liters": 3,
        "cost": 2,
        "price_per_unit": 4,
        "fill_level": 2,
    },
    "financing_records": {"amount": 2},
    "fuel_records": {
        "odometer_km": 2,
        "engine_hours": 1,
        "liters": 3,
        "propane_liters": 3,
        "tank_size_kg": 3,
        "kwh": 3,
        "soc_start_pct": 2,
        "soc_end_pct": 2,
        "battery_soh_pct": 2,
        "cost": 2,
        "rebate": 2,
        "price_per_unit": 4,
        "outside_temp_c": 2,
        "obc_l_per_100km": 4,
        "obc_avg_speed_kmh": 1,
    },
    "hours_records": {"engine_hours": 1},
    "insurance_coverages": {
        "limit_primary": 2,
        "limit_secondary": 2,
        "deductible": 2,
        "premium": 2,
    },
    "insurance_policies": {"premium_amount": 2},
    "insurance_policy_vehicles": {"premium_share": 2, "deductible": 2},
    "livelink_devices": {"movement_baseline_km": 2},
    "livelink_topic_maps": {"scale": 6, "value_offset": 6},
    "location_points": {
        "latitude": 6,
        "longitude": 6,
        "speed": 2,
        "heading": 1,
        "altitude": 1,
    },
    "odometer_records": {"odometer_km": 2},
    "reminder_pack_items": {"interval_km": 2, "interval_hours": 1},
    "service_line_items": {"cost": 2},
    "service_visits": {
        "odometer_km": 2,
        "engine_hours": 1,
        "total_cost": 2,
        "tax_amount": 2,
        "shop_supplies": 2,
        "misc_fees": 2,
    },
    "spot_rental_billings": {
        "monthly_rate": 2,
        "electric": 2,
        "water": 2,
        "waste": 2,
        "total": 2,
    },
    "spot_rentals": {
        "nightly_rate": 2,
        "weekly_rate": 2,
        "monthly_rate": 2,
        "electric": 2,
        "water": 2,
        "waste": 2,
        "total_cost": 2,
    },
    "supply_purchases": {"quantity": 13, "total_cost": 2},
    "supply_usages": {"quantity": 13, "unit_cost_snapshot": 4, "cost_snapshot": 2},
    "tax_records": {"amount": 2},
    "tire_mount_periods": {
        "mounted_odometer_km": 2,
        "dismounted_odometer_km": 2,
        "mounted_hours": 1,
        "dismounted_hours": 1,
    },
    "tire_readings": {
        "odometer_km": 2,
        "engine_hours": 1,
        "tread_depth_mm": 2,
        "pressure_kpa": 2,
    },
    "tires": {"tread_depth_mm": 2, "pressure_kpa": 2, "min_tread_mm": 2},
    "toll_transactions": {"amount": 2},
    "trailer_details": {"gvwr_kg": 3, "length_m": 3, "width_m": 3, "height_m": 3},
    "vehicle_maintenance_rules": {"interval_km": 2, "interval_hours": 1},
    "vehicle_reminders": {
        "due_mileage_km": 2,
        "due_hours": 1,
        "tread_depth_mm": 2,
        "tread_threshold_mm": 2,
        "anchor_odometer_km": 2,
        "anchor_hours": 1,
        "start_odometer_km": 2,
        "start_hours": 1,
        "completed_odometer_km": 2,
        "completed_hours": 1,
    },
    "vehicles": {
        "current_hours": 1,
        "purchase_price": 2,
        "sold_price": 2,
        "msrp_base": 2,
        "msrp_options": 2,
        "msrp_total": 2,
        "fuel_economy_city_l_per_100km": 4,
        "fuel_economy_highway_l_per_100km": 4,
        "fuel_economy_combined_l_per_100km": 4,
        "destination_charge": 2,
        "window_sticker_confidence_score": 2,
        "archive_sale_price": 2,
        "def_tank_capacity_liters": 2,
        "oil_capacity_liters": 2,
        "lug_nut_torque_nm": 1,
        "last_milestone_notified_km": 2,
    },
    "warranty_records": {"mileage_limit_km": 2},
}


def _get_fallback_engine() -> Engine:
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def rounded(value: float, scale: int) -> float | None:
    """The float rounded to `scale` places, or None when it's already there or can't be.

    Through its repr, so 1.005 rounds as the 1.005 that was typed, not the double below it.
    """
    number = Decimal(repr(value))
    if not number.is_finite():
        return None
    try:
        quantized = number.quantize(Decimal(1).scaleb(-scale), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return None
    if quantized == number:
        return None
    # SQLite has no decimal type; a float is what the app's own writes store.
    return float(quantized)


def _round_table(conn: Connection, table: str, scales: dict[str, int]) -> int:
    """Round every listed column of one table on the caller's connection. Returns values written."""
    columns = list(scales)
    # Only REAL values can carry extra places: an INTEGER can't, and TEXT isn't a number.
    reals = " OR ".join(f"typeof({column}) = 'real'" for column in columns)
    head = f"SELECT rowid, {', '.join(columns)} FROM {table} WHERE"
    tail = f"({reals}) ORDER BY rowid LIMIT :batch"
    first = text(f"{head} {tail}")
    # A bare rowid > :after, no `:after IS NULL OR`: the OR makes SQLite scan from
    # the top every batch, which goes quadratic on a big location_points.
    later = text(f"{head} rowid > :after AND {tail}")
    written = 0
    after: int | None = None
    while True:
        if after is None:
            rows = conn.execute(first, {"batch": BATCH}).all()
        else:
            rows = conn.execute(later, {"after": after, "batch": BATCH}).all()
        if not rows:
            return written
        for index, column in enumerate(columns, start=1):
            updates = []
            for row in rows:
                value = row[index]
                if not isinstance(value, float):
                    continue
                new = rounded(value, scales[column])
                if new is not None:
                    updates.append({"rowid": row[0], "value": new})
            if updates:
                conn.execute(
                    text(f"UPDATE {table} SET {column} = :value WHERE rowid = :rowid"), updates
                )
                written += len(updates)
        after = rows[-1][0]


def upgrade(engine: Engine | None = None) -> None:
    """Round each listed table's Numeric columns to their scales, a table per transaction."""
    if engine is None:
        engine = _get_fallback_engine()

    if engine.dialect.name != "sqlite":
        logger.info(
            "136: %s rounds to the column's scale itself; nothing to do", engine.dialect.name
        )
        return

    inspector = inspect(engine)
    total = 0
    for table, scales in COLUMNS.items():
        if not inspector.has_table(table):
            logger.info("136: %s missing; skip", table)
            continue
        present = {c["name"] for c in inspector.get_columns(table)}
        for column in sorted(scales.keys() - present):
            logger.info("136: %s.%s missing; skip", table, column)
        here = {column: scale for column, scale in scales.items() if column in present}
        if not here:
            continue
        with engine.begin() as conn:
            written = _round_table(conn, table, here)
        if written:
            logger.info("136: %s, %s value(s) rounded", table, written)
        total += written
    logger.info("136: rounded %s stored value(s) to their column's scale", total)


def downgrade() -> None:  # pragma: no cover
    raise NotImplementedError("Migration 136 is forward-only.")


if __name__ == "__main__":
    upgrade()
