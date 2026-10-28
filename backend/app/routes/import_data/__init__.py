"""Data import routes for MyGarage.

CSV/JSON exports from v2.26.2+ carry a schema marker:
  - CSV: leading `units_version` column on every row (= "3" for SI metric)
  - JSON: top-level `"export_version"` and `"units"` keys

JSON backups are still schema 5 and still resolve units file-wide, below.
CSV moved to schema 6 for issue #152: a per-quantity unit preference makes a
single `metric`/`imperial` marker unable to describe a file whose distance is
miles and whose volume is litres, so a v6 CSV column names its own unit with
a phase-1 vocabulary token (`Odometer (mi)`, `Volume (gal_uk)`).

`app.utils.csv_units` owns that decision for the four unit-bearing CSV pairs
(service, fuel, DEF, odometer). It resolves the unit from the FILE alone --
header token, then marker, then `units_version`, then a narrow inference over
the column names -- and refuses the upload rather than guessing when the file
is ambiguous. It never reads the importing account's preferences: doing that
is what once multiplied an old US-gallon backup by 4.54609 on a
UK-configured instance and wrote the result into canonical storage
permanently.

This importer still accepts every older shape: v3-v5 metric
(`Odometer (km)` / `Liters` / `Price Per Liter`) and legacy v2 imperial
(`Mileage` / `Gallons` / `Price Per Gallon`), which is converted on ingest
because the ORM columns are metric.
"""

# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedClass=false

# isort: off
# Each route module adds its routes to the shared router as it imports, so this
# order is the order the served schema and /docs list them in: CSV, the JSON
# backup, third party. The committed openapi.json is sorted and won't notice; the
# route-order dump does.
from app.routes.import_data import csv_routes, vehicle_json, third_party

# isort: on
from app.routes.import_data._common import _ImportBoundError, _within_api_bounds, limiter, router
from app.routes.import_data._matching import _COLUMN_SCALE, _column_step, _same_figure
from app.routes.import_data.third_party import _persist_parsed_fuel

__all__ = [
    "csv_routes",
    "vehicle_json",
    "third_party",
    "router",
    "limiter",
    "_COLUMN_SCALE",
    "_ImportBoundError",
    "_column_step",
    "_persist_parsed_fuel",
    "_same_figure",
    "_within_api_bounds",
]
