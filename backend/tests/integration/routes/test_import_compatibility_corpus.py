"""Every CSV shape MyGarage has ever emitted still imports to the right number.

Issue #152 phase 2b, task 4. An export bug shows a wrong number once; an
import bug writes a wrong number into canonical storage permanently. This
file is the matrix: {service, fuel, DEF, odometer} x {every distinct header
row that pair has emitted since v2.14.0}, each cell carrying version-specific
sentinel values and a hand-written expected canonical outcome.

How the shape list was derived
------------------------------
An AST walk over EVERY revision of `backend/app/routes/export.py` and
`backend/app/routes/reports.py` (oldest first), pulling the literal
`headers = [...]` list and every literal `writer.writerow([...])` out of the
named export functions and printing each `(pair, header-tuple)` the first
time it appears. Unfiltered: 16 distinct tuples in `export.py`, 4 in
`reports.py`. The script and its verbatim output live beside this task's
report. Nothing here is inferred from what a version "probably" looked like.

A header TUPLE is not the same as a file SHAPE. `generate_csv_stream`
prepends `units_version` from `f0a8b3b` on and `unit_system` from `f6c8a05`
on, and `to_imperial` rewrites the unit-bearing names on an `?units=imperial`
export, so one header tuple can appear as several files. The fixtures below
enumerate file shapes; the walk enumerates the tuples underneath them.

Timeline, with the commit that first emitted each tuple:

  ad13de6  2025-12-02  v2.14.0, the initial commit. No `units_version` column
                       at all; values were imperial because storage was.
  26d0ee5  2026-01-20  Fuel drops the derived `MPG` column and gains
                       `Is Hauling` / `Fuel Type`. First shipped v2.20.1.
  4a45b70  2026-02-11  DEF export added, still unversioned and imperial. The
                       plan's floor table said DEF postdates v2; it does not.
  2d46bae  2026-02-12  The service-history REPORT drops from eight columns to
                       seven. The seven-column form is the one R9 refuses.
  3fc799c  2026-02-13  Service renames `Service Type` -> `Category` and
                       collapses `Vendor Name` / `Vendor Location` into
                       `Vendor`. This is the seven-column PRIMARY shape R9 has
                       to tell apart from that report. First shipped v2.21.1.
  6f04e53  2026-04-25  v3: metric-canonical storage (#70). `units_version`
                       appears; `Mileage`/`Gallons`/`Price Per Gallon` become
                       `Odometer (km)`/`Liters`/`Price Per Liter`. There is
                       still NO `unit_system` column.
  f0a8b3b  2026-05-05  v4 pre-marker: extended fuel columns (#69). Still no
                       `unit_system`, so a v4 file's units come from
                       `units_version` alone -- R4 step 3.
  ffee906  2026-07-13  v4 pre-marker + `Rebate`. Shipped in v2.31.0, and it is
                       the LAST unmarked fuel export MyGarage ever released,
                       so it carries more R4-step-3 risk than any other fuel
                       file in the wild.
  42d1def  2026-07-31  v4 pre-marker + `Engine Hours`, fuel and service.
                       Superseded by `f6c8a05` five days later, so it appears
                       in no tag; covered anyway, because a dev instance
                       running from `main` could have exported one.
  f6c8a05  2026-08-05  v4 + marker: `unit_system` column and the imperial
                       header rename map (#128). First files whose header row
                       can be imperial while the schema is >= 3.
  d997b40  2026-08-17  v4 + marker + the EV/charge columns, with `Fuel Type`
                       still present. Superseded by `a88f4bd` five days later,
                       so it too appears in no tag.
  a88f4bd  2026-08-22  v5: the legacy `Fuel Type` column is retired.
  75b8920  2026-08-24  v5 + `imperial_uk`: the UK gallon flavour gets its own
                       marker. This is the ONLY version that ever emitted it.
  49a4166  2026-08-26  v6: per-column vocabulary tokens, marker `metric` |
                       `imperial` | `custom`.

The `reports.py` CSVs: all four tuples covered, none importable
---------------------------------------------------------------
All four report tuples are covered, and since 2026-08-26 all four are
REFUSED rather than imported. They live in `REPORT_SHAPES` (plus the
seven-column service-history form, which keeps its own entry in `REJECTIONS`
because it is additionally unit-ambiguous), not in `CORPUS`.

The rule used to turn on ambiguity, and three of the four were unambiguous:
`download_all_records_csv` renamed `Mileage` to `Odometer (km)` in the same
commit that made its values canonical (`6f04e53`), so neither of its eras is
ambiguous, and the eight-column `download_service_history_csv` form
(`ad13de6`..`2d46bae`, 23 tagged releases) was retired 2026-02-12, before the
metric migration on 2026-04-25, so it can only hold miles. All three
therefore imported.

Ambiguity was the wrong criterion. What those files import AS is garbage:
the all-records report interleaves fuel rows with service rows, so importing
one writes a service visit per fill-up, stamped `service_category=
'Maintenance'`. The rule is now flat -- a report CSV is never importable, in
any era -- and the compatibility guarantee below covers backups, which is
what it was always about.

What the tuple signature still protects, and what pins it: `service-v2` (the
seven-column PRIMARY export, same names as the seven-column report in a
different order) and `service-v2-initial` (eight names overlapping the
eight-column report's, different order, `Vendor Location` not `Vendor
Phone`). Both import, and would not if the signature were column membership.

Factors, from `UnitConverter` (the app's rounded constants, not the exact SI
definitions). Every expected value below was computed from these BY HAND and
never routed back through the code under test:

  MILES_TO_KM                 1.60934
  US_GALLONS_TO_LITERS        3.78541
  UK_GALLONS_TO_LITERS        4.54609
  US_MPG_TO_L100KM_NUMERATOR  235.214
  UK_MPG_TO_L100KM_NUMERATOR  282.481
  Fahrenheit                  (F - 32) * 5 / 9

Assertions are on the value that LANDS IN THE DATABASE, read back through a
session that never saw the write (see `_one`) so the column's own scale has
been applied, because that is what the compatibility guarantee is actually
about. An HTTP 200 proves only that nothing raised.
"""

from __future__ import annotations

import csv
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from decimal import Decimal
from io import BytesIO, StringIO

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.def_record import DEFRecord
from app.models.fuel import FuelRecord
from app.models.hours import HoursRecord
from app.models.odometer import OdometerRecord
from app.models.service_line_item import ServiceLineItem
from app.models.service_visit import ServiceVisit
from app.models.vehicle import Vehicle
from app.models.vendor import Vendor

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

# One vendor name for the whole corpus, so teardown can remove exactly the
# rows these fixtures create without touching another suite's vendors.
CORPUS_VENDOR = "CorpusShop"


@dataclass(frozen=True)
class Shape:
    """One CSV shape some version of MyGarage emitted, and what it must mean.

    `evidence` is the commit whose `export.py` emitted `header` verbatim.
    `expected` maps an ORM attribute to the exact canonical value that must
    land in storage, as a literal string; `None` asserts the column stays
    NULL.
    """

    pair: str
    evidence: str
    header: str
    row: str
    expected: Mapping[str, str | None]

    @property
    def body(self) -> str:
        """The whole upload: header row, one data row, trailing newline."""
        return f"{self.header}\n{self.row}\n"


# --------------------------------------------------------------------------
# Header rows, verbatim. Repeated in full rather than assembled from parts:
# a shape is defined by its exact bytes, and a builder would let a
# transcription error hide behind shared code.
# --------------------------------------------------------------------------

_SVC_V2_INITIAL = "Date,Service Type,Description,Mileage,Cost,Vendor Name,Vendor Location,Notes"
_SVC_V2 = "Date,Category,Description,Mileage,Cost,Vendor,Notes"
_SVC_V3 = "units_version,Date,Category,Description,Odometer (km),Cost,Vendor,Notes"
_SVC_MARKER_KM = (
    "units_version,unit_system,Date,Category,Description,Odometer (km),"
    "Engine Hours,Cost,Vendor,Notes"
)
_SVC_MARKER_MI = (
    "units_version,unit_system,Date,Category,Description,Mileage,Engine Hours,Cost,Vendor,Notes"
)
_SVC_V6_MI = (
    "units_version,unit_system,Date,Category,Description,Odometer (mi),"
    "Engine Hours,Cost,Vendor,Notes"
)

_SVC_V4_PREMARKER_HOURS = (
    "units_version,Date,Category,Description,Odometer (km),Engine Hours,Cost,Vendor,Notes"
)

_SVC_REPORT_HISTORY_V2 = "Date,Mileage,Service Type,Description,Cost,Vendor Name,Vendor Phone,Notes"
_SVC_REPORT_ALL_V2 = "Date,Type,Category,Description,Cost,Mileage,Vendor"
_SVC_REPORT_ALL_V3 = "Date,Type,Category,Description,Cost,Odometer (km),Vendor"

_ODO_V2 = "Date,Reading,Notes"
_ODO_V2_MILEAGE = "Date,Mileage,Notes"
_ODO_V3 = "units_version,Date,Reading (km),Notes"
_ODO_MARKER_KM = "units_version,unit_system,Date,Reading (km),Notes"
_ODO_MARKER_BARE = "units_version,unit_system,Date,Reading,Notes"
_ODO_V6_MI = "units_version,unit_system,Date,Reading (mi),Notes"

_DEF_V2 = "Date,Mileage,Gallons,Price Per Unit,Total Cost,Fill Level,Source,Brand,Notes"
_DEF_V3 = (
    "units_version,Date,Odometer (km),Liters,Price Per Unit,Total Cost,"
    "Fill Level,Source,Brand,Notes"
)
_DEF_MARKER_METRIC = (
    "units_version,unit_system,Date,Odometer (km),Liters,Price Per Unit,"
    "Total Cost,Fill Level,Source,Brand,Notes"
)
_DEF_MARKER_IMPERIAL = (
    "units_version,unit_system,Date,Mileage,Gallons,Price Per Unit,"
    "Total Cost,Fill Level,Source,Brand,Notes"
)
_DEF_V6_METRIC = (
    "units_version,unit_system,Date,Odometer (km),Volume (L),Price Per Unit (L),"
    "Total Cost,Fill Level,Source,Brand,Notes"
)
_DEF_V6_US = (
    "units_version,unit_system,Date,Odometer (mi),Volume (gal_us),Price Per Unit (gal_us),"
    "Total Cost,Fill Level,Source,Brand,Notes"
)
_DEF_V6_CUSTOM = (
    "units_version,unit_system,Date,Odometer (km),Volume (gal_uk),Price Per Unit (gal_uk),"
    "Total Cost,Fill Level,Source,Brand,Notes"
)

_FUEL_V2_INITIAL = (
    "Date,Mileage,Gallons,Price Per Gallon,Total Cost,MPG,Full Tank,Missed Fill-up,Notes"
)
_FUEL_V2 = (
    "Date,Mileage,Gallons,Price Per Gallon,Total Cost,Full Tank,Missed Fill-up,"
    "Is Hauling,Fuel Type,Notes"
)
_FUEL_V3 = (
    "units_version,Date,Odometer (km),Liters,Price Per Liter,Total Cost,Full Tank,"
    "Missed Fill-up,Is Hauling,Fuel Type,Notes"
)
_FUEL_V4_PREMARKER = (
    "units_version,Date,Filled At,Odometer (km),Liters,Price Per Liter,Total Cost,"
    "Full Tank,Missed Fill-up,Is Hauling,Fuel Type,Fuel Type Used,Station ID,Station,"
    "Driver ID,Driver,Payment Method,Trip Type,Outside Temp (C),OBC L/100km,"
    "OBC Avg Speed (km/h),OBC Trip Duration (s),Notes"
)
_FUEL_V4_PREMARKER_REBATE = (
    "units_version,Date,Filled At,Odometer (km),Liters,Price Per Liter,Rebate,Total Cost,"
    "Full Tank,Missed Fill-up,Is Hauling,Fuel Type,Fuel Type Used,Station ID,Station,"
    "Driver ID,Driver,Payment Method,Trip Type,Outside Temp (C),OBC L/100km,"
    "OBC Avg Speed (km/h),OBC Trip Duration (s),Notes"
)
_FUEL_V4_PREMARKER_HOURS = (
    "units_version,Date,Filled At,Odometer (km),Engine Hours,Liters,Price Per Liter,Rebate,"
    "Total Cost,Full Tank,Missed Fill-up,Is Hauling,Fuel Type,Fuel Type Used,Station ID,"
    "Station,Driver ID,Driver,Payment Method,Trip Type,Outside Temp (C),OBC L/100km,"
    "OBC Avg Speed (km/h),OBC Trip Duration (s),Notes"
)
_FUEL_V4_MARKER_EV_IMPERIAL = (
    "units_version,unit_system,Date,Filled At,Mileage,Engine Hours,Gallons,"
    "Price Per Gallon,Rebate,Total Cost,Full Tank,Missed Fill-up,Is Hauling,Fuel Type,"
    "Fuel Type Used,Station ID,Station,Driver ID,Driver,Payment Method,Trip Type,"
    "Outside Temp (F),OBC MPG,OBC Avg Speed (mph),OBC Trip Duration (s),"
    "SOC Start (%),SOC End (%),Charge Level,Charge Location,Battery SOH (%),Notes"
)
_FUEL_V4_MARKER_METRIC = (
    "units_version,unit_system,Date,Filled At,Odometer (km),Engine Hours,Liters,"
    "Price Per Liter,Rebate,Total Cost,Full Tank,Missed Fill-up,Is Hauling,Fuel Type,"
    "Fuel Type Used,Station ID,Station,Driver ID,Driver,Payment Method,Trip Type,"
    "Outside Temp (C),OBC L/100km,OBC Avg Speed (km/h),OBC Trip Duration (s),Notes"
)
_FUEL_V4_MARKER_IMPERIAL = (
    "units_version,unit_system,Date,Filled At,Mileage,Engine Hours,Gallons,"
    "Price Per Gallon,Rebate,Total Cost,Full Tank,Missed Fill-up,Is Hauling,Fuel Type,"
    "Fuel Type Used,Station ID,Station,Driver ID,Driver,Payment Method,Trip Type,"
    "Outside Temp (F),OBC MPG,OBC Avg Speed (mph),OBC Trip Duration (s),Notes"
)
_FUEL_V5_METRIC = (
    "units_version,unit_system,Date,Filled At,Odometer (km),Engine Hours,Liters,"
    "Price Per Liter,Rebate,Total Cost,Full Tank,Missed Fill-up,Is Hauling,"
    "Fuel Type Used,Station ID,Station,Driver ID,Driver,Payment Method,Trip Type,"
    "Outside Temp (C),OBC L/100km,OBC Avg Speed (km/h),OBC Trip Duration (s),"
    "SOC Start (%),SOC End (%),Charge Level,Charge Location,Battery SOH (%),Notes"
)
_FUEL_V5_IMPERIAL = (
    "units_version,unit_system,Date,Filled At,Mileage,Engine Hours,Gallons,"
    "Price Per Gallon,Rebate,Total Cost,Full Tank,Missed Fill-up,Is Hauling,"
    "Fuel Type Used,Station ID,Station,Driver ID,Driver,Payment Method,Trip Type,"
    "Outside Temp (F),OBC MPG,OBC Avg Speed (mph),OBC Trip Duration (s),"
    "SOC Start (%),SOC End (%),Charge Level,Charge Location,Battery SOH (%),Notes"
)
_FUEL_V6_METRIC = (
    "units_version,unit_system,Date,Filled At,Odometer (km),Engine Hours,Volume (L),"
    "Price Per Unit (L),Rebate,Total Cost,Full Tank,Missed Fill-up,Is Hauling,"
    "Fuel Type Used,Station ID,Station,Driver ID,Driver,Payment Method,Trip Type,"
    "Outside Temp (c),OBC Economy (l_100km),OBC Avg Speed (kmh),OBC Trip Duration (s),"
    "SOC Start (%),SOC End (%),Charge Level,Charge Location,Battery SOH (%),Notes"
)
_FUEL_V6_US = (
    "units_version,unit_system,Date,Filled At,Odometer (mi),Engine Hours,Volume (gal_us),"
    "Price Per Unit (gal_us),Rebate,Total Cost,Full Tank,Missed Fill-up,Is Hauling,"
    "Fuel Type Used,Station ID,Station,Driver ID,Driver,Payment Method,Trip Type,"
    "Outside Temp (f),OBC Economy (mpg_us),OBC Avg Speed (mph),OBC Trip Duration (s),"
    "SOC Start (%),SOC End (%),Charge Level,Charge Location,Battery SOH (%),Notes"
)
_FUEL_V6_CUSTOM = (
    "units_version,unit_system,Date,Filled At,Odometer (km),Engine Hours,Volume (gal_uk),"
    "Price Per Unit (gal_uk),Rebate,Total Cost,Full Tank,Missed Fill-up,Is Hauling,"
    "Fuel Type Used,Station ID,Station,Driver ID,Driver,Payment Method,Trip Type,"
    "Outside Temp (f),OBC Economy (mpg_uk),OBC Avg Speed (mph),OBC Trip Duration (s),"
    "SOC Start (%),SOC End (%),Charge Level,Charge Location,Battery SOH (%),Notes"
)


# --------------------------------------------------------------------------
# The matrix. Keys are the naming contract `<pair>-v<N>[-<variant>]`, and are
# also the pytest parametrize ids, so a failure names the shape directly.
# --------------------------------------------------------------------------

CORPUS: Mapping[str, Shape] = {
    # -- service ----------------------------------------------------------
    "service-v2-initial": Shape(
        pair="service",
        evidence="ad13de6",
        header=_SVC_V2_INITIAL,
        # 110 mi * 1.60934 = 177.0274 km
        row=f"2026-01-05,Oil Change,Synthetic oil,110,49.99,{CORPUS_VENDOR},Springfield,v2.14.0",
        expected={"odometer_km": "177.03"},
    ),
    "service-v2": Shape(
        pair="service",
        evidence="3fc799c",
        header=_SVC_V2,
        # 120 mi * 1.60934 = 193.1208 km. Same seven columns as the rejected
        # service-history report, in a different order (R9).
        row=f"2026-01-06,Maintenance,Tyre rotation,120,25.00,{CORPUS_VENDOR},v2.20 backup",
        expected={"odometer_km": "193.12"},
    ),
    "service-v3": Shape(
        pair="service",
        evidence="6f04e53",
        header=_SVC_V3,
        row=f"3,2026-01-07,Maintenance,Brake fluid,1300.50,80.00,{CORPUS_VENDOR},",
        expected={"odometer_km": "1300.50"},
    ),
    "service-v4-premarker": Shape(
        pair="service",
        evidence="f0a8b3b",
        header=_SVC_V3,
        # Identical header row to v3; only the version cell moved. The unit
        # therefore comes from `units_version` alone (R4 step 3).
        row=f"4,2026-01-08,Inspection,Annual,1400.25,60.00,{CORPUS_VENDOR},",
        expected={"odometer_km": "1400.25"},
    ),
    "service-v4-premarker-engine-hours": Shape(
        pair="service",
        evidence="42d1def",
        header=_SVC_V4_PREMARKER_HOURS,
        # `Engine Hours` before `unit_system` existed. Never in a tag: it
        # landed 2026-07-31 and `f6c8a05` superseded it 2026-08-05, with no
        # tag cut between the two. Covered anyway, because the operator runs
        # a second instance from `main` and an export from that window would
        # be in exactly this shape.
        row=f"4,2026-01-17,Maintenance,Transmission fluid,1800.35,20.5,175.00,{CORPUS_VENDOR},",
        expected={"odometer_km": "1800.35"},
    ),
    "service-v4-marker-metric": Shape(
        pair="service",
        evidence="f6c8a05",
        header=_SVC_MARKER_KM,
        row=f"4,metric,2026-01-09,Maintenance,Coolant,1500.75,12.5,95.00,{CORPUS_VENDOR},",
        expected={"odometer_km": "1500.75"},
    ),
    "service-v4-marker-imperial": Shape(
        pair="service",
        evidence="f6c8a05",
        header=_SVC_MARKER_MI,
        # 130 mi * 1.60934 = 209.2142 km
        row=f"4,imperial,2026-01-10,Maintenance,Plugs,130,13.5,120.00,{CORPUS_VENDOR},",
        expected={"odometer_km": "209.21"},
    ),
    "service-v5-metric": Shape(
        pair="service",
        evidence="a88f4bd",
        header=_SVC_MARKER_KM,
        row=f"5,metric,2026-01-11,Detailing,Wax,1600.40,14.5,150.00,{CORPUS_VENDOR},",
        expected={"odometer_km": "1600.40"},
    ),
    "service-v5-imperial": Shape(
        pair="service",
        evidence="a88f4bd",
        header=_SVC_MARKER_MI,
        # 140 mi * 1.60934 = 225.3076 km
        row=f"5,imperial,2026-01-12,Maintenance,Filter,140,15.5,35.00,{CORPUS_VENDOR},",
        expected={"odometer_km": "225.31"},
    ),
    "service-v5-imperial-uk": Shape(
        pair="service",
        evidence="75b8920",
        header=_SVC_MARKER_MI,
        # 150 mi * 1.60934 = 241.401 km. The gallon flavour cannot reach a
        # distance column, so imperial_uk must read exactly like imperial.
        row=f"5,imperial_uk,2026-01-13,Maintenance,Belt,150,16.5,210.00,{CORPUS_VENDOR},",
        expected={"odometer_km": "241.40"},
    ),
    "service-v6-metric": Shape(
        pair="service",
        evidence="49a4166",
        header=_SVC_MARKER_KM,
        row=f"6,metric,2026-01-14,Maintenance,Oil,1700.60,17.5,55.00,{CORPUS_VENDOR},",
        expected={"odometer_km": "1700.60"},
    ),
    "service-v6-imperial": Shape(
        pair="service",
        evidence="49a4166",
        header=_SVC_V6_MI,
        # 160 mi * 1.60934 = 257.4944 km
        row=f"6,imperial,2026-01-15,Maintenance,Oil,160,18.5,55.00,{CORPUS_VENDOR},",
        expected={"odometer_km": "257.49"},
    ),
    "service-v6-custom": Shape(
        pair="service",
        evidence="49a4166",
        header=_SVC_V6_MI,
        # 170 mi * 1.60934 = 273.5878 km
        row=f"6,custom,2026-01-16,Maintenance,Oil,170,19.5,55.00,{CORPUS_VENDOR},",
        expected={"odometer_km": "273.59"},
    ),
    # The three `reports.py` shapes that used to sit here moved to REJECTIONS
    # below. They are report exports, not backups, and a report CSV is never
    # importable in any era: see `REPORT_SHAPES` and the note above it.
    # -- odometer ---------------------------------------------------------
    "odometer-v2-bare-reading": Shape(
        pair="odometer",
        evidence="ad13de6",
        header=_ODO_V2,
        # 180 mi * 1.60934 = 289.6812 km. R9 DEFINES this shape as miles.
        row="2026-02-01,180,v2 standalone odometer",
        expected={"odometer_km": "289.68"},
    ),
    "odometer-v2-mileage-alias": Shape(
        pair="odometer",
        evidence="(never emitted)",
        header=_ODO_V2_MILEAGE,
        # 190 mi * 1.60934 = 305.7746 km. No odometer export ever wrote
        # `Mileage`, but the importer has accepted it since v3 and a
        # hand-built sheet can carry it, so the alias is pinned here.
        row="2026-02-02,190,importer-only alias",
        expected={"odometer_km": "305.77"},
    ),
    "odometer-v3": Shape(
        pair="odometer",
        evidence="6f04e53",
        header=_ODO_V3,
        row="3,2026-02-03,2100.25,",
        expected={"odometer_km": "2100.25"},
    ),
    "odometer-v4-premarker": Shape(
        pair="odometer",
        evidence="f0a8b3b",
        header=_ODO_V3,
        row="4,2026-02-04,2200.50,",
        expected={"odometer_km": "2200.50"},
    ),
    "odometer-v4-marker-metric": Shape(
        pair="odometer",
        evidence="f6c8a05",
        header=_ODO_MARKER_KM,
        row="4,metric,2026-02-05,2300.75,",
        expected={"odometer_km": "2300.75"},
    ),
    "odometer-v4-marker-imperial": Shape(
        pair="odometer",
        evidence="f6c8a05",
        header=_ODO_MARKER_BARE,
        # 210 mi * 1.60934 = 337.9614 km. A bare `Reading` that is NOT the v2
        # shape: the marker says imperial outright, so R9's definition is
        # never consulted.
        row="4,imperial,2026-02-06,210,",
        expected={"odometer_km": "337.96"},
    ),
    "odometer-v5-metric": Shape(
        pair="odometer",
        evidence="a88f4bd",
        header=_ODO_MARKER_KM,
        row="5,metric,2026-02-07,2400.10,",
        expected={"odometer_km": "2400.10"},
    ),
    "odometer-v5-imperial": Shape(
        pair="odometer",
        evidence="a88f4bd",
        header=_ODO_MARKER_BARE,
        # 220 mi * 1.60934 = 354.0548 km
        row="5,imperial,2026-02-08,220,",
        expected={"odometer_km": "354.05"},
    ),
    "odometer-v5-imperial-uk": Shape(
        pair="odometer",
        evidence="75b8920",
        header=_ODO_MARKER_BARE,
        # 230 mi * 1.60934 = 370.1482 km
        row="5,imperial_uk,2026-02-09,230,",
        expected={"odometer_km": "370.15"},
    ),
    "odometer-v6-metric": Shape(
        pair="odometer",
        evidence="49a4166",
        header=_ODO_MARKER_KM,
        row="6,metric,2026-02-10,2500.20,",
        expected={"odometer_km": "2500.20"},
    ),
    "odometer-v6-imperial": Shape(
        pair="odometer",
        evidence="49a4166",
        header=_ODO_V6_MI,
        # 240 mi * 1.60934 = 386.2416 km
        row="6,imperial,2026-02-11,240,",
        expected={"odometer_km": "386.24"},
    ),
    "odometer-v6-custom": Shape(
        pair="odometer",
        evidence="49a4166",
        header=_ODO_V6_MI,
        # 260 mi * 1.60934 = 418.4284 km
        row="6,custom,2026-02-12,260,",
        expected={"odometer_km": "418.43"},
    ),
    # -- DEF --------------------------------------------------------------
    "def-v2": Shape(
        pair="def",
        evidence="4a45b70",
        header=_DEF_V2,
        # DEF DID have an unversioned shape: the export landed 2026-02-11,
        # ten weeks before v3. 270 mi * 1.60934 = 434.5218 km;
        # 8 US gal * 3.78541 = 30.28328 L; 7.57082 / 3.78541 = 2 per litre.
        row="2026-03-01,270,8,7.57082,60.57,0.75,Pump,BlueDEF,v2 DEF backup",
        expected={
            "odometer_km": "434.52",
            "liters": "30.283",
            "price_per_unit": "2.000",
        },
    ),
    "def-v3": Shape(
        pair="def",
        evidence="6f04e53",
        header=_DEF_V3,
        row="3,2026-03-02,3100.25,9.500,0.850,8.08,0.80,Pump,BlueDEF,",
        expected={
            "odometer_km": "3100.25",
            "liters": "9.500",
            "price_per_unit": "0.850",
        },
    ),
    "def-v4-premarker": Shape(
        pair="def",
        evidence="f0a8b3b",
        header=_DEF_V3,
        row="4,2026-03-03,3200.50,10.250,0.900,9.23,0.70,Pump,BlueDEF,",
        expected={
            "odometer_km": "3200.50",
            "liters": "10.250",
            "price_per_unit": "0.900",
        },
    ),
    "def-v4-marker-metric": Shape(
        pair="def",
        evidence="f6c8a05",
        header=_DEF_MARKER_METRIC,
        row="4,metric,2026-03-04,3300.75,11.125,0.950,10.57,0.65,Pump,BlueDEF,",
        expected={
            "odometer_km": "3300.75",
            "liters": "11.125",
            "price_per_unit": "0.950",
        },
    ),
    "def-v4-marker-imperial": Shape(
        pair="def",
        evidence="f6c8a05",
        header=_DEF_MARKER_IMPERIAL,
        # 280 mi * 1.60934 = 450.6152 km; 9 US gal * 3.78541 = 34.06869 L;
        # 11.35623 / 3.78541 = 3 per litre. `Price Per Unit` keeps its name
        # on imperial export, so its unit can only come from the marker.
        row="4,imperial,2026-03-05,280,9,11.35623,102.21,0.60,Pump,BlueDEF,",
        expected={
            "odometer_km": "450.62",
            "liters": "34.069",
            "price_per_unit": "3.000",
        },
    ),
    "def-v5-metric": Shape(
        pair="def",
        evidence="a88f4bd",
        header=_DEF_MARKER_METRIC,
        row="5,metric,2026-03-06,3400.10,12.500,1.050,13.13,0.55,Pump,BlueDEF,",
        expected={
            "odometer_km": "3400.10",
            "liters": "12.500",
            "price_per_unit": "1.050",
        },
    ),
    "def-v5-imperial": Shape(
        pair="def",
        evidence="a88f4bd",
        header=_DEF_MARKER_IMPERIAL,
        # 290 mi * 1.60934 = 466.7086 km; 11 US gal * 3.78541 = 41.63951 L;
        # 3.78541 / 3.78541 = 1 per litre.
        row="5,imperial,2026-03-07,290,11,3.78541,41.64,0.50,Pump,BlueDEF,",
        expected={
            "odometer_km": "466.71",
            "liters": "41.640",
            "price_per_unit": "1.000",
        },
    ),
    "def-v5-imperial-uk": Shape(
        pair="def",
        evidence="75b8920",
        header=_DEF_MARKER_IMPERIAL,
        # 310 mi * 1.60934 = 498.8954 km; 12 UK gal * 4.54609 = 54.55308 L;
        # 9.09218 / 4.54609 = 2 per litre. Reading these as US gallons
        # instead understates the volume by 17%.
        row="5,imperial_uk,2026-03-08,310,12,9.09218,109.11,0.45,Pump,BlueDEF,",
        expected={
            "odometer_km": "498.90",
            "liters": "54.553",
            "price_per_unit": "2.000",
        },
    ),
    "def-v6-metric": Shape(
        pair="def",
        evidence="49a4166",
        header=_DEF_V6_METRIC,
        row="6,metric,2026-03-09,3500.20,13.750,1.150,15.81,0.40,Pump,BlueDEF,",
        expected={
            "odometer_km": "3500.20",
            "liters": "13.750",
            "price_per_unit": "1.150",
        },
    ),
    "def-v6-imperial": Shape(
        pair="def",
        evidence="49a4166",
        header=_DEF_V6_US,
        # 320 mi * 1.60934 = 514.9888 km; 14 US gal * 3.78541 = 52.99574 L;
        # 7.57082 / 3.78541 = 2 per litre.
        row="6,imperial,2026-03-10,320,14,7.57082,105.99,0.35,Pump,BlueDEF,",
        expected={
            "odometer_km": "514.99",
            "liters": "52.996",
            "price_per_unit": "2.000",
        },
    ),
    "def-v6-custom": Shape(
        pair="def",
        evidence="49a4166",
        header=_DEF_V6_CUSTOM,
        # Kilometres AND UK gallons in one file, which no marker can express:
        # 16 UK gal * 4.54609 = 72.73744 L; 13.63827 / 4.54609 = 3 per litre.
        row="6,custom,2026-03-11,3600.30,16,13.63827,218.21,0.30,Pump,BlueDEF,",
        expected={
            "odometer_km": "3600.30",
            "liters": "72.737",
            "price_per_unit": "3.000",
        },
    ),
    # -- fuel -------------------------------------------------------------
    "fuel-v2-initial": Shape(
        pair="fuel",
        evidence="ad13de6",
        header=_FUEL_V2_INITIAL,
        # 330 mi * 1.60934 = 531.0822 km; 10 US gal * 3.78541 = 37.8541 L;
        # 3.78541 / 3.78541 = 1 per litre. The bare `MPG` column was a
        # DERIVED figure and has never been imported: it must stay ignored,
        # not be mistaken for the `OBC MPG` consumption column.
        row="2026-04-01,330,10,3.78541,37.85,25.5,Yes,No,v2.14.0 fuel",
        expected={
            "odometer_km": "531.08",
            "liters": "37.854",
            "price_per_unit": "1.000",
            "obc_l_per_100km": None,
        },
    ),
    "fuel-v2": Shape(
        pair="fuel",
        evidence="26d0ee5",
        header=_FUEL_V2,
        # 340 mi * 1.60934 = 547.1756 km; 12 US gal * 3.78541 = 45.42492 L;
        # 7.57082 / 3.78541 = 2 per litre.
        row="2026-04-02,340,12,7.57082,90.85,Yes,No,No,Gasoline,v2.20 fuel",
        expected={
            "odometer_km": "547.18",
            "liters": "45.425",
            "price_per_unit": "2.000",
        },
    ),
    "fuel-v3": Shape(
        pair="fuel",
        evidence="6f04e53",
        header=_FUEL_V3,
        row="3,2026-04-03,4100.25,42.500,1.450,61.63,Yes,No,No,Gasoline,",
        expected={
            "odometer_km": "4100.25",
            "liters": "42.500",
            "price_per_unit": "1.450",
        },
    ),
    "fuel-v4-premarker": Shape(
        pair="fuel",
        evidence="f0a8b3b",
        header=_FUEL_V4_PREMARKER,
        # No `unit_system` column at all: metric comes from `units_version`
        # alone. `Outside Temp (C)`, `OBC L/100km` and `OBC Avg Speed (km/h)`
        # name their own units, and their parenthesised neighbours
        # (`OBC Trip Duration (s)`) must pass through untouched (R6).
        row=(
            "4,2026-04-04,2026-04-04T08:30:00,4200.50,43.250,1.500,64.88,Yes,No,No,"
            "Gasoline,gasoline,,Shell,,Alex,Card,Commute,18.5,7.25,85.5,3600,"
        ),
        expected={
            "odometer_km": "4200.50",
            "liters": "43.250",
            "price_per_unit": "1.500",
            "outside_temp_c": "18.5",
            "obc_l_per_100km": "7.25",
            "obc_avg_speed_kmh": "85.5",
        },
    ),
    "fuel-v4-premarker-rebate": Shape(
        pair="fuel",
        evidence="ffee906",
        header=_FUEL_V4_PREMARKER_REBATE,
        # Shipped in v2.31.0 (and v2.31.0-rc3, v3.0.0-rc1). The LAST unmarked
        # fuel export MyGarage released, so of every fuel file a user could
        # still be holding, this is the one whose units rest entirely on
        # `units_version` with no marker to fall back on (R4 step 3).
        row=(
            "4,2026-04-13,2026-04-13T13:00:00,4700.15,47.125,1.700,0.50,80.11,Yes,No,No,"
            "Gasoline,gasoline,,Shell,,Alex,Card,Commute,17.5,6.75,87.5,4500,"
        ),
        expected={
            "odometer_km": "4700.15",
            "liters": "47.125",
            "price_per_unit": "1.700",
            "outside_temp_c": "17.5",
            "obc_l_per_100km": "6.75",
            "obc_avg_speed_kmh": "87.5",
        },
    ),
    "fuel-v4-premarker-engine-hours": Shape(
        pair="fuel",
        evidence="42d1def",
        header=_FUEL_V4_PREMARKER_HOURS,
        # `Engine Hours` added while the file was still unmarked. Never in a
        # tag (see `service-v4-premarker-engine-hours`), covered for the same
        # reason.
        row=(
            "4,2026-04-14,2026-04-14T13:30:00,4800.25,29.5,48.375,1.750,0.50,84.16,Yes,No,No,"
            "Gasoline,gasoline,,Shell,,Alex,Card,Commute,16.5,6.50,89.5,4600,"
        ),
        expected={
            "odometer_km": "4800.25",
            "liters": "48.375",
            "price_per_unit": "1.750",
            "outside_temp_c": "16.5",
            "obc_l_per_100km": "6.50",
            "obc_avg_speed_kmh": "89.5",
        },
    ),
    "fuel-v4-marker-metric": Shape(
        pair="fuel",
        evidence="f6c8a05",
        header=_FUEL_V4_MARKER_METRIC,
        row=(
            "4,metric,2026-04-05,2026-04-05T09:00:00,4300.75,21.5,44.125,1.550,0.00,68.39,"
            "Yes,No,No,Gasoline,gasoline,,Shell,,Alex,Card,Commute,19.5,7.50,90.5,3700,"
        ),
        expected={
            "odometer_km": "4300.75",
            "liters": "44.125",
            "price_per_unit": "1.550",
            "outside_temp_c": "19.5",
            "obc_l_per_100km": "7.50",
            "obc_avg_speed_kmh": "90.5",
        },
    ),
    "fuel-v4-marker-imperial": Shape(
        pair="fuel",
        evidence="f6c8a05",
        header=_FUEL_V4_MARKER_IMPERIAL,
        # 350 mi * 1.60934 = 563.269 km; 15 US gal * 3.78541 = 56.78115 L;
        # 11.35623 / 3.78541 = 3 per litre; (68 - 32) * 5/9 = 20 C;
        # 235.214 / 23.5214 = 10.00 L/100km; 60 mph * 1.60934 = 96.5604 km/h.
        row=(
            "4,imperial,2026-04-06,2026-04-06T09:30:00,350,22.5,15,11.35623,0.00,170.34,"
            "Yes,No,No,Gasoline,gasoline,,Shell,,Alex,Card,Commute,68,23.5214,60,3800,"
        ),
        expected={
            "odometer_km": "563.27",
            "liters": "56.781",
            "price_per_unit": "3.000",
            "outside_temp_c": "20.0",
            "obc_l_per_100km": "10.00",
            "obc_avg_speed_kmh": "96.6",
        },
    ),
    "fuel-v4-marker-ev-fuel-type": Shape(
        pair="fuel",
        evidence="d997b40",
        header=_FUEL_V4_MARKER_EV_IMPERIAL,
        # The five-day shape: EV/charge columns arrived while the legacy
        # `Fuel Type` column was still being written, so this file carries
        # both. `a88f4bd` retired `Fuel Type` and moved the schema to 5
        # before any tag was cut, so it appears in no release. Its unit
        # resolution is the same as v5 imperial; what it adds is proof that
        # the extra dimensionless column does not disturb the R6 allowlist.
        # 390 mi * 1.60934 = 627.6426 km; 24 US gal * 3.78541 = 90.84984 L;
        # 15.14164 / 3.78541 = 4 per litre; (140 - 32) * 5/9 = 60 C;
        # 235.214 / 47.0428 = 5.00 L/100km; 90 mph * 1.60934 = 144.8406.
        row=(
            "4,imperial,2026-04-15,2026-04-15T14:00:00,390,30.5,24,15.14164,0.50,363.40,"
            "Yes,No,No,Gasoline,gasoline,,Shell,,Alex,Card,Commute,140,47.0428,90,4700,"
            "10.0,90.0,L2,Home,99.0,"
        ),
        expected={
            "odometer_km": "627.64",
            "liters": "90.850",
            "price_per_unit": "4.000",
            "outside_temp_c": "60.0",
            "obc_l_per_100km": "5.00",
            "obc_avg_speed_kmh": "144.8",
        },
    ),
    "fuel-v5-metric": Shape(
        pair="fuel",
        evidence="a88f4bd",
        header=_FUEL_V5_METRIC,
        row=(
            "5,metric,2026-04-07,2026-04-07T10:00:00,4400.10,23.5,45.500,1.600,0.00,72.80,"
            "Yes,No,No,gasoline,,Shell,,Alex,Card,Commute,20.5,7.75,92.5,3900,"
            "10.0,90.0,L2,Home,99.0,"
        ),
        expected={
            "odometer_km": "4400.10",
            "liters": "45.500",
            "price_per_unit": "1.600",
            "outside_temp_c": "20.5",
            "obc_l_per_100km": "7.75",
            "obc_avg_speed_kmh": "92.5",
        },
    ),
    "fuel-v5-imperial": Shape(
        pair="fuel",
        evidence="a88f4bd",
        header=_FUEL_V5_IMPERIAL,
        # 360 mi * 1.60934 = 579.3624 km; 16 US gal * 3.78541 = 60.56656 L;
        # 7.57082 / 3.78541 = 2 per litre; (50 - 32) * 5/9 = 10 C;
        # 235.214 / 11.7607 = 20.00 L/100km; 55 mph * 1.60934 = 88.5137 km/h.
        row=(
            "5,imperial,2026-04-08,2026-04-08T10:30:00,360,24.5,16,7.57082,0.00,121.13,"
            "Yes,No,No,gasoline,,Shell,,Alex,Card,Commute,50,11.7607,55,4000,"
            "10.0,90.0,L2,Home,99.0,"
        ),
        expected={
            "odometer_km": "579.36",
            "liters": "60.567",
            "price_per_unit": "2.000",
            "outside_temp_c": "10.0",
            "obc_l_per_100km": "20.00",
            "obc_avg_speed_kmh": "88.5",
        },
    ),
    "fuel-v5-imperial-uk": Shape(
        pair="fuel",
        evidence="75b8920",
        header=_FUEL_V5_IMPERIAL,
        # The only version that ever emitted `imperial_uk`. It settles BOTH
        # the gallon (volume and price) and the MPG numerator, which are two
        # separate code paths: 18 UK gal * 4.54609 = 81.82962 L;
        # 13.63827 / 4.54609 = 3 per litre; 282.481 / 14.12405 = 20.00
        # L/100km. 370 mi * 1.60934 = 595.4558 km; (86 - 32) * 5/9 = 30 C;
        # 65 mph * 1.60934 = 104.6071 km/h.
        row=(
            "5,imperial_uk,2026-04-09,2026-04-09T11:00:00,370,25.5,18,13.63827,0.00,245.49,"
            "Yes,No,No,gasoline,,Shell,,Alex,Card,Commute,86,14.12405,65,4100,"
            "10.0,90.0,L2,Home,99.0,"
        ),
        expected={
            "odometer_km": "595.46",
            "liters": "81.830",
            "price_per_unit": "3.000",
            "outside_temp_c": "30.0",
            "obc_l_per_100km": "20.00",
            "obc_avg_speed_kmh": "104.6",
        },
    ),
    "fuel-v6-metric": Shape(
        pair="fuel",
        evidence="49a4166",
        header=_FUEL_V6_METRIC,
        row=(
            "6,metric,2026-04-10,2026-04-10T11:30:00,4500.20,26.5,46.750,1.650,0.00,77.14,"
            "Yes,No,No,gasoline,,Shell,,Alex,Card,Commute,21.5,8.25,94.5,4200,"
            "10.0,90.0,L2,Home,99.0,"
        ),
        expected={
            "odometer_km": "4500.20",
            "liters": "46.750",
            "price_per_unit": "1.650",
            "outside_temp_c": "21.5",
            "obc_l_per_100km": "8.25",
            "obc_avg_speed_kmh": "94.5",
        },
    ),
    "fuel-v6-imperial": Shape(
        pair="fuel",
        evidence="49a4166",
        header=_FUEL_V6_US,
        # 380 mi * 1.60934 = 611.5492 km; 20 US gal * 3.78541 = 75.7082 L;
        # 11.35623 / 3.78541 = 3 per litre; (104 - 32) * 5/9 = 40 C;
        # 235.214 / 23.5214 = 10.00 L/100km; 70 mph * 1.60934 = 112.6538.
        row=(
            "6,imperial,2026-04-11,2026-04-11T12:00:00,380,27.5,20,11.35623,0.00,227.12,"
            "Yes,No,No,gasoline,,Shell,,Alex,Card,Commute,104,23.5214,70,4300,"
            "10.0,90.0,L2,Home,99.0,"
        ),
        expected={
            "odometer_km": "611.55",
            "liters": "75.708",
            "price_per_unit": "3.000",
            "outside_temp_c": "40.0",
            "obc_l_per_100km": "10.00",
            "obc_avg_speed_kmh": "112.7",
        },
    ),
    "fuel-v6-custom": Shape(
        pair="fuel",
        evidence="49a4166",
        header=_FUEL_V6_CUSTOM,
        # The shape that only v6 can express, and the reason this phase
        # exists: kilometres, UK gallons, Fahrenheit, UK MPG and mph in one
        # file. No `unit_system` value describes it, so every column has to
        # be read from its own token. 22 UK gal * 4.54609 = 100.01398 L;
        # 9.09218 / 4.54609 = 2 per litre; (122 - 32) * 5/9 = 50 C;
        # 282.481 / 28.2481 = 10.00 L/100km; 80 mph * 1.60934 = 128.7472.
        row=(
            "6,custom,2026-04-12,2026-04-12T12:30:00,4600.30,28.5,22,9.09218,0.00,200.03,"
            "Yes,No,No,gasoline,,Shell,,Alex,Card,Commute,122,28.2481,80,4400,"
            "10.0,90.0,L2,Home,99.0,"
        ),
        expected={
            "odometer_km": "4600.30",
            "liters": "100.014",
            "price_per_unit": "2.000",
            "outside_temp_c": "50.0",
            "obc_l_per_100km": "10.00",
            "obc_avg_speed_kmh": "128.7",
        },
    ),
}

MODELS = {
    "service": ServiceVisit,
    "fuel": FuelRecord,
    "def": DEFRecord,
    "odometer": OdometerRecord,
}

# A stable 17-character VIN per fixture, so a leaked row names its own shape
# in the primary key rather than colliding with another fixture's vehicle.
VINS = {fixture_id: f"CORPUS{index:011d}" for index, fixture_id in enumerate(CORPUS)}


@pytest.fixture(autouse=True)
def _reset_import_rate_limit():
    """Clear the shared import limiter between tests.

    `routes/import_data.py` has one module-level 20/minute limiter across
    every import endpoint, and this file posts far more than that. Mirrors
    the precedent in `test_import_data.py` and `test_import_csv_v6_units.py`.
    """
    from app.routes.import_data import limiter as import_limiter

    storage = import_limiter._storage
    storage.storage.clear()
    storage.expirations.clear()
    if hasattr(storage, "events"):
        storage.events.clear()


@asynccontextmanager
async def _vehicle(db_session: AsyncSession, user_id: object, vin: str) -> AsyncIterator[str]:
    """A throwaway diesel vehicle, torn down in `finally`.

    The suite shares one database with no per-test rollback, so every row a
    fixture writes has to be removed explicitly. That includes the `Vendor`
    the service importer creates from the CSV's vendor column, which is a
    global row rather than a per-vehicle one.
    """
    db_session.add(
        Vehicle(
            vin=vin,
            user_id=user_id,
            nickname=vin,
            vehicle_type="Car",
            year=2024,
            make="Test",
            model="Corpus",
            # Diesel so the DEF importer's fuel-type gate accepts the vehicle.
            fuel_type="diesel",
        )
    )
    await db_session.commit()
    try:
        yield vin
    finally:
        visit_ids = (
            (await db_session.execute(select(ServiceVisit.id).where(ServiceVisit.vin == vin)))
            .scalars()
            .all()
        )
        if visit_ids:
            await db_session.execute(
                delete(ServiceLineItem).where(ServiceLineItem.visit_id.in_(visit_ids))
            )
        for model in (ServiceVisit, FuelRecord, DEFRecord, OdometerRecord, HoursRecord):
            await db_session.execute(delete(model).where(model.vin == vin))
        await db_session.execute(delete(Vehicle).where(Vehicle.vin == vin))
        await db_session.execute(delete(Vendor).where(Vendor.name == CORPUS_VENDOR))
        await db_session.commit()


async def _post(client: AsyncClient, headers, vin: str, pair: str, body: str):
    """Upload one CSV to one importer, never skipping duplicates."""
    return await client.post(
        f"/api/import/vehicles/{vin}/{pair}/csv",
        headers=headers,
        files={"file": (f"{pair}.csv", BytesIO(body.encode()), "text/csv")},
        data={"skip_duplicates": "false"},
    )


async def _one(sessionmaker, model, vin: str):
    """The single row `model` holds for `vin`, read through a FRESH session.

    Not the session the request ran on. The app and the test share one
    `expire_on_commit=False` session, whose identity map still holds the
    instance the route built, so a read through it is only as trustworthy as
    whatever happened to expire that instance along the way. A separate
    session has an empty identity map and can answer only from the database,
    which is the thing the compatibility guarantee is actually about: what
    LANDED in canonical storage, at the column's own scale.
    """
    async with sessionmaker() as fresh:
        return (await fresh.execute(select(model).where(model.vin == vin))).scalars().one()


# --------------------------------------------------------------------------
# The corpus itself.
# --------------------------------------------------------------------------


class TestEmittedShapeCorpus:
    """{service, fuel, DEF, odometer} x {every shape that pair has emitted}."""

    @pytest.mark.parametrize("fixture_id", list(CORPUS))
    def test_the_fixture_is_well_formed(self, fixture_id: str) -> None:
        """Header and data row have the same number of cells.

        A miscounted comma in a hand-written fixture shifts every later
        column silently, and `csv.DictReader` would pad or truncate rather
        than complain. Guarding it here means a corpus failure is always a
        parser finding and never a typo.
        """
        shape = CORPUS[fixture_id]
        rows = list(csv.reader(StringIO(shape.body)))
        assert len(rows) == 2, f"{fixture_id}: expected exactly one data row"
        assert len(rows[0]) == len(rows[1]), (
            f"{fixture_id}: {len(rows[0])} header cells vs {len(rows[1])} data cells"
        )

    @pytest.mark.parametrize("fixture_id", list(CORPUS))
    async def test_the_shape_imports_to_the_expected_canonical_value(
        self, fixture_id: str, client, auth_headers, test_user, db_session, test_sessionmaker
    ) -> None:
        """The compatibility guarantee, asserted on stored canonical values."""
        shape = CORPUS[fixture_id]
        async with _vehicle(db_session, test_user["id"], VINS[fixture_id]) as vin:
            resp = await _post(client, auth_headers, vin, shape.pair, shape.body)
            assert resp.status_code == 200, resp.text
            assert resp.json()["success_count"] == 1, resp.json()

            record = await _one(test_sessionmaker, MODELS[shape.pair], vin)
            for attribute, expected in shape.expected.items():
                actual = getattr(record, attribute)
                if expected is None:
                    assert actual is None, f"{fixture_id}.{attribute}: expected NULL, got {actual}"
                    continue
                assert actual is not None, (
                    f"{fixture_id}.{attribute}: expected {expected}, got NULL"
                )
                assert Decimal(actual) == Decimal(expected), (
                    f"{fixture_id}.{attribute}: expected {expected}, got {actual}"
                )


class TestEveryRowIsConvertedNotJustTheFirst:
    """A file's units reach row 3, not only the row the reader saw first.

    This does NOT prove R5's pre-scan, and an earlier name claiming it did
    was wrong. `unit_system` and `units_version` are written into every data
    row, so an implementation that reads the context off row 1 and one that
    pre-scans every row emit byte-identical results on any file whose rows
    agree. No valid file can separate them, because R5's design REJECTS any
    file whose rows disagree, which is what makes the distinction unobservable
    from the accepting side.

    The pre-scan itself is pinned by the two rejection fixtures that need it:
    `rows-disagree-unit-system` and `rows-disagree-units-version` in
    `TestR8Rejections`. Only a reader that has looked at every row before
    writing anything can raise those.

    What this class does pin is narrower and still real: the resolved context
    is applied to every row rather than to the first one alone. Mutations M2,
    M3 and M7 all break it.
    """

    async def test_all_three_rows_of_one_uk_file_convert_identically(
        self, client, auth_headers, test_user, db_session, test_sessionmaker
    ) -> None:
        """Three identical UK-gallon volumes, all three converted the same.

        12 UK gal * 4.54609 = 54.55308 L each. Under US gallons any of them
        would land at 45.425, so a row left unconverted, or converted under
        the wrong flavour, shows up here.
        """
        async with _vehicle(db_session, test_user["id"], "CORPUSMULTIROW01") as vin:
            body = (
                f"{_DEF_MARKER_IMPERIAL}\n"
                "5,imperial_uk,2026-03-20,100,12,9.09218,109.11,0.45,Pump,BlueDEF,\n"
                "5,imperial_uk,2026-03-21,200,12,9.09218,109.11,0.45,Pump,BlueDEF,\n"
                "5,imperial_uk,2026-03-22,300,12,9.09218,109.11,0.45,Pump,BlueDEF,\n"
            )
            resp = await _post(client, auth_headers, vin, "def", body)
            assert resp.status_code == 200, resp.text
            assert resp.json()["success_count"] == 3

            async with test_sessionmaker() as fresh:
                records = (
                    (
                        await fresh.execute(
                            select(DEFRecord).where(DEFRecord.vin == vin).order_by(DEFRecord.date)
                        )
                    )
                    .scalars()
                    .all()
                )
            assert len(records) == 3
            for record in records:
                assert Decimal(record.liters) == Decimal("54.553")
                assert Decimal(record.price_per_unit) == Decimal("2.000")


# --------------------------------------------------------------------------
# R8: one rejection fixture per rule, with the exact user-visible message.
# Hand-written literals, not `csv_units`' own constants: a reworded error is
# a change to what the operator reads and should have to be made on purpose.
# --------------------------------------------------------------------------

REJECTIONS: Mapping[str, tuple[str, str, str]] = {
    # rule -> (import pair, CSV body, exact detail string)
    "unrecognised-header-token": (
        "fuel",
        "units_version,unit_system,Date,Odometer (furlong)\n6,custom,2026-05-01,100\n",
        "CSV column 'Odometer (furlong)' declares an unrecognised unit 'furlong'. "
        "Expected one of: km, mi.",
    ),
    "recognised-token-wrong-quantity": (
        "fuel",
        "units_version,unit_system,Date,Odometer (gal_us)\n6,custom,2026-05-02,100\n",
        "CSV column 'Odometer (gal_us)' declares unit 'gal_us', which is not a distance unit. "
        "Expected one of: km, mi.",
    ),
    "unrecognised-marker": (
        "fuel",
        "units_version,unit_system,Date,Gallons\n5,imperial_ukk,2026-05-03,10\n",
        "Unrecognised unit_system marker 'imperial_ukk'. "
        "Expected one of: custom, imperial, imperial_uk, metric.",
    ),
    "custom-marker-tokenless-column": (
        "fuel",
        "units_version,unit_system,Date,Liters\n6,custom,2026-05-04,10\n",
        "unit_system 'custom' says the units are in the headers, but column 'Liters' "
        "carries no unit token.",
    ),
    "two-columns-one-quantity": (
        "fuel",
        "units_version,unit_system,Date,Odometer (km),Mileage\n6,custom,2026-05-05,100,62\n",
        "CSV has more than one distance column: 'Mileage', 'Odometer (km)'. "
        "Keep exactly one and re-import.",
    ),
    "duplicate-header": (
        "fuel",
        "units_version,unit_system,Date,Odometer (mi),Odometer (mi)\n6,custom,2026-05-06,100,100\n",
        "CSV has a duplicate 'Odometer (mi)' column. Remove the duplicate and re-import.",
    ),
    "rows-disagree-unit-system": (
        "fuel",
        "units_version,unit_system,Date,Gallons\n5,metric,2026-05-07,10\n5,imperial,2026-05-08,10\n",
        "CSV rows disagree about unit_system: 'imperial', 'metric'. "
        "One file must be in one unit system.",
    ),
    "rows-disagree-units-version": (
        "fuel",
        "units_version,Date,Liters\n2,2026-05-09,10\n5,2026-05-10,10\n",
        "CSV rows disagree about units_version: '2', '5'. One file must be one schema version.",
    ),
    "ambiguous-unversioned-report": (
        "service",
        "Date,Mileage,Category,Description,Cost,Vendor,Notes\n"
        "2026-05-11,100,Maintenance,Oil,10.00,Shop,\n",
        "This header row matches the unversioned service-history report export. "
        "Its 'Mileage' column is miles in older files and kilometres in newer ones, "
        "with nothing in the file to tell them apart, so importing it could "
        "silently store the wrong distance. Re-export the vehicle from "
        "Export > Service records instead, which carries a units marker.",
    ),
}

# --------------------------------------------------------------------------
# Every OTHER shape `reports.py` has emitted. These sat in CORPUS until
# 2026-08-26 asserting the canonical values they imported to; they are now
# refused, and this is a deliberate compatibility change, not a regression.
#
# The old rule refused a report only when its UNITS were ambiguous, which let
# the all-records report -- the one that actually corrupts -- keep importing.
# It returns HTTP 200 and writes one service visit per fuel fill-up, stamped
# `service_category='Maintenance'` because the importer ignores the report's
# `Type` column, so the fabricated rows are indistinguishable from real
# maintenance in the UI and in every cost aggregate.
#
# The rule is now flat: a report CSV is never importable, in any era. The
# eight-column service-history form is included even though it is unambiguous
# (retired 2026-02-12, before the metric migration, so it can only hold
# miles), because a guard that refuses the newer report and accepts the older
# one cannot be explained to a user, and "a report is not a backup" can.
#
# What must still import, and is pinned elsewhere in this file: the v2 PRIMARY
# service export (`service-v2`), whose seven names match the seven-column
# report's in a different order, and the v2 INITIAL service export
# (`service-v2-initial`), whose eight names overlap the eight-column report's
# in a different order and carry `Vendor Location` where the report carries
# `Vendor Phone`. Both survive because the signature is the ordered tuple.
# --------------------------------------------------------------------------

_SERVICE_HISTORY_REPORT_REFUSAL = (
    "This header row matches the service-history report export, which is a "
    "printable summary rather than a backup: it flattens each service visit "
    "into one row per line item and carries columns the importer does not "
    "consume, so importing it would create malformed records. Re-export the "
    "vehicle from Export > Service records instead."
)
_ALL_RECORDS_REPORT_REFUSAL = (
    "This header row matches the all-records report export, which is a "
    "printable summary rather than a backup: it interleaves fuel rows with "
    "service rows in one file, so importing it would create a service visit "
    "out of every fill-up. Re-export the vehicle from Export instead, one "
    "record type at a time."
)

REPORT_SHAPES: Mapping[str, tuple[str, str, str]] = {
    # id -> (evidence commit, CSV body, exact detail string)
    #
    # `download_service_history_csv`, EIGHT columns, `ad13de6`..`2d46bae`
    # across 23 tagged releases. Used to import as 430 mi -> 692.02 km.
    "report-service-history-v2-eight-column": (
        "ad13de6",
        f"{_SVC_REPORT_HISTORY_V2}\n"
        f"2026-01-22,430,Oil Change,Synthetic oil,49.99,{CORPUS_VENDOR},555-0100,\n",
        _SERVICE_HISTORY_REPORT_REFUSAL,
    ),
    # `download_all_records_csv`, `Mileage` era, `ad13de6`..`6f04e53`.
    # Used to import as 410 mi -> 659.83 km.
    "report-all-records-v2": (
        "ad13de6",
        f"{_SVC_REPORT_ALL_V2}\n"
        f"2026-01-20,Service,Maintenance,Oil change,49.99,410,{CORPUS_VENDOR}\n",
        _ALL_RECORDS_REPORT_REFUSAL,
    ),
    # `download_all_records_csv`, `Odometer (km)` era, `6f04e53`..v6.
    # Used to import as 3700.45 km unchanged.
    "report-all-records-v3": (
        "6f04e53",
        f"{_SVC_REPORT_ALL_V3}\n"
        f"2026-01-21,Service,Maintenance,Oil change,49.99,3700.45,{CORPUS_VENDOR}\n",
        _ALL_RECORDS_REPORT_REFUSAL,
    ),
}

REPORT_SHAPE_VINS = {name: f"REPORT{index:011d}" for index, name in enumerate(REPORT_SHAPES)}

REJECTION_VINS = {rule: f"REJECT{index:011d}" for index, rule in enumerate(REJECTIONS)}


class TestR8Rejections:
    """Every R8 rule refuses the file and says why, in words an operator reads."""

    @pytest.mark.parametrize("rule", list(REJECTIONS))
    async def test_the_rule_rejects_with_its_exact_message(
        self, rule: str, client, auth_headers, test_user, db_session, test_sessionmaker
    ) -> None:
        pair, body, detail = REJECTIONS[rule]
        async with _vehicle(db_session, test_user["id"], REJECTION_VINS[rule]) as vin:
            resp = await _post(client, auth_headers, vin, pair, body)
            assert resp.status_code == 400, resp.text
            assert resp.json()["detail"] == detail
            # Rejection lands before any ORM write, so nothing is half-imported.
            async with test_sessionmaker() as fresh:
                leaked = (
                    (await fresh.execute(select(MODELS[pair]).where(MODELS[pair].vin == vin)))
                    .scalars()
                    .all()
                )
            assert leaked == []


class TestReportShapesAreNeverImportable:
    """Every era of both report exports is refused, and writes nothing.

    These three shapes imported successfully until 2026-08-26 and this file
    asserted the canonical values they produced. The values were real; the
    ROWS were not. Flipping them is the deliberate compatibility change that
    closes the corruption path, and the assertions below are what stop it
    being quietly reopened.
    """

    @pytest.mark.parametrize("name", list(REPORT_SHAPES))
    async def test_the_report_shape_is_refused_and_writes_nothing(
        self, name: str, client, auth_headers, test_user, db_session, test_sessionmaker
    ) -> None:
        _evidence, body, detail = REPORT_SHAPES[name]
        async with _vehicle(db_session, test_user["id"], REPORT_SHAPE_VINS[name]) as vin:
            resp = await _post(client, auth_headers, vin, "service", body)
            assert resp.status_code == 400, resp.text
            assert resp.json()["detail"] == detail
            async with test_sessionmaker() as fresh:
                leaked = (
                    (await fresh.execute(select(ServiceVisit).where(ServiceVisit.vin == vin)))
                    .scalars()
                    .all()
                )
            assert leaked == []

    async def test_a_realistic_pre_v6_all_records_file_creates_no_phantom_visits(
        self, client, auth_headers, test_user, db_session, test_sessionmaker
    ) -> None:
        """The scenario the flat rule exists for, at full size.

        A real all-records export interleaves fuel rows with service rows. The
        single-row fixtures above cannot show what that costs: before the
        guard covered this shape, this exact body returned HTTP 200 with
        `success_count: 3` and wrote THREE service visits, two of them
        fabricated from fill-ups and every one of them stamped
        `service_category='Maintenance'`, because the importer ignores the
        report's `Type` column and coerces the unknown category. Those rows
        are indistinguishable from real maintenance in the UI and in every
        cost aggregate.
        """
        body = (
            f"{_SVC_REPORT_ALL_V3}\n"
            f"2026-07-01,Service,Maintenance,Oil change,49.99,12345.00,{CORPUS_VENDOR}\n"
            "2026-07-02,Fuel,Fuel,40.000L,55.00,800.00,\n"
            "2026-07-03,Fuel,Fuel,20.000L,30.00,900.00,\n"
        )
        async with _vehicle(db_session, test_user["id"], "REPORTPHANTOM001") as vin:
            resp = await _post(client, auth_headers, vin, "service", body)
            assert resp.status_code == 400, resp.text
            assert "all-records report export" in resp.json()["detail"]
            async with test_sessionmaker() as fresh:
                visits = (
                    (await fresh.execute(select(ServiceVisit).where(ServiceVisit.vin == vin)))
                    .scalars()
                    .all()
                )
            assert visits == [], f"expected no visits, got {[v.odometer_km for v in visits]}"


# --------------------------------------------------------------------------
# R9: the ambiguous report and the v2 backup it must not take down with it.
# --------------------------------------------------------------------------


class TestR9OrderedTupleSignature:
    """The rejected report is identified by ORDER, never by column membership.

    `reports.download_service_history_csv` has written
    `Date,Mileage,Category,Description,Cost,Vendor,Notes` since `2d46bae`
    (2026-02-12). It has NOT always written that: from `ad13de6` until
    `2d46bae` it wrote eight columns
    (`Date,Mileage,Service Type,Description,Cost,Vendor Name,Vendor Phone,Notes`),
    which is a different tuple and is not rejected, because it was retired
    before the metric migration and so can only ever hold miles. See
    `service-v2-report-service-history`.

    The seven-column form is the ambiguous one: it spans the migration with
    its `Mileage` header unchanged. The v2 PRIMARY service export (`3fc799c`,
    2026-02-13) writes the same seven names as
    `Date,Category,Description,Mileage,Cost,Vendor,Notes`, one day later and
    in a different order. Matching on the set instead of the tuple would
    reject every v2 backup restore along with the report.
    """

    REPORT = "Date,Mileage,Category,Description,Cost,Vendor,Notes"
    V2_PRIMARY = "Date,Category,Description,Mileage,Cost,Vendor,Notes"
    OTHER_PERMUTATION = "Date,Category,Mileage,Description,Cost,Vendor,Notes"

    async def test_the_report_tuple_is_rejected(
        self, client, auth_headers, test_user, db_session
    ) -> None:
        async with _vehicle(db_session, test_user["id"], "R9REPORT00000001") as vin:
            body = f"{self.REPORT}\n2026-06-01,100,Maintenance,Oil,10.00,{CORPUS_VENDOR},\n"
            resp = await _post(client, auth_headers, vin, "service", body)
            assert resp.status_code == 400, resp.text
            assert "unversioned service-history report" in resp.json()["detail"]

    async def test_the_v2_primary_backup_still_imports(
        self, client, auth_headers, test_user, db_session, test_sessionmaker
    ) -> None:
        """Same seven names, v2's order. 320 mi * 1.60934 = 514.9888 km."""
        async with _vehicle(db_session, test_user["id"], "R9V2PRIMARY00001") as vin:
            body = f"{self.V2_PRIMARY}\n2026-06-02,Maintenance,Oil,320,10.00,{CORPUS_VENDOR},\n"
            resp = await _post(client, auth_headers, vin, "service", body)
            assert resp.status_code == 200, resp.text
            visit = await _one(test_sessionmaker, ServiceVisit, vin)
            assert Decimal(visit.odometer_km) == Decimal("514.99")

    async def test_another_permutation_of_the_same_names_also_imports(
        self, client, auth_headers, test_user, db_session, test_sessionmaker
    ) -> None:
        """Membership is not the signature, so no other ordering is caught.

        MyGarage never emitted this order; it is here because a set-based
        signature would swallow it too, and only an ordered-tuple signature
        distinguishes the one file that is genuinely ambiguous.
        330 mi * 1.60934 = 531.0822 km.
        """
        async with _vehicle(db_session, test_user["id"], "R9PERMUTATION001") as vin:
            body = (
                f"{self.OTHER_PERMUTATION}\n2026-06-03,Maintenance,330,Oil,10.00,{CORPUS_VENDOR},\n"
            )
            resp = await _post(client, auth_headers, vin, "service", body)
            assert resp.status_code == 200, resp.text
            visit = await _one(test_sessionmaker, ServiceVisit, vin)
            assert Decimal(visit.odometer_km) == Decimal("531.08")
