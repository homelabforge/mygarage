"""Resolve the instance gallon flavour from settings.

Phase 0 of the custom-units work replaces `UnitConverter.set_gallon_standard()`,
which mutated process-global class state. This module is the single explicit
source of that value for backend callers. `resolve_gallon_flavour(db)` carries
no caller identity, so when phase 1 moves this to a per-user preference, it
MUST extend this function's signature to accept the caller's identity (e.g.
the current `User`) as an explicit parameter -- there is no way to resolve a
per-user value from `db` alone. Resolving the user from ambient request-local
context instead (a `ContextVar` or similar) would reintroduce, one layer up,
the exact ambient-mutable-state defect these eight commits exist to eliminate:
a value that changes depending on when you read it rather than what was
explicitly passed in. Extend the signature; do not reach for ambient state.

Gallon-consumer classification (phase 0 deliverable)
----------------------------------------------------

Three classes, each with a different source of truth. Phase 1 must not collapse
them into one.

1. USER PREFERENCE -- resolve from the caller's UnitSet (phase 1) or, today,
   from this module:
     - services/notifications/dispatcher.py  DEF-low volume
     - services/widget_aggregation.py        widget v1/v2 MPG fields
     - routes/export.py                      CSV export values and marker

2. FILE OR REQUEST MARKER -- the flavour travels with the data, never from a
   preference:
     - routes/import_data.py `_row_gallons_to_liters`  reads the file's own
       `unit_system` marker (CSV import path); already explicit, already
       correct, do not change
     - routes/export.py `?units=` query parameter      caller's explicit request

3. INTRINSICALLY US -- a fixed constant, never a preference:
     - EPA / window-sticker MPG figures (vehicles.fuel_economy_*), which are US
       MPG by definition regardless of where the user lives. The OCR path
       (services/window_sticker_ocr.py `_MPG_TO_L100KM = Decimal("235.214583")`)
       computes this with its OWN literal, not `UnitConverter.
       US_MPG_TO_L100KM_NUMERATOR` (`Decimal("235.214")`) -- the two constants
       differ in the fifth significant digit. A phase-1 "unify the constants"
       pass touches this value and will silently change already-stored figures
       if it isn't accounted for.
     - webhook `gal` ingress, which documents US gallons in its contract
     - migrations/053, a frozen historical transform with a literal numerator
     - routes/import_data.py `_maybe_gal_to_l` / `_maybe_per_gal_to_per_l`
       (legacy-v2 JSON backup import, `import_vehicle_json`): unconditionally
       US whenever `is_legacy_v2`. Same reasoning as `_row_gallons_to_liters`
       above -- pre-v3 files predate the UK gallon option entirely -- but
       unlike the CSV path there is no per-file marker for that era, so it
       cannot become class 2 the way CSV did.
     - services/import_adapters/fuel_csv.py `GAL_TO_L` (Fuelio + Drivvo
       "Gallons" column fallback, used only when the source file has no
       "Liters" column): unconditionally US, with no code comment establishing
       whether that is deliberate. OPEN QUESTION for phase 1: the same import
       routes (routes/import_data.py `import_fuelio_csv` / `import_drivvo_csv`)
       already let the caller declare `odometer_unit` and `decimal_separator`
       for other columns these formats leave ambiguous, but there is no
       equivalent declared parameter for gallons -- so this may belong in
       class 2 instead, as a caller-declared marker, rather than class 3. Not
       resolved here; do not guess, ask before changing it.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import Setting
from app.utils.units import GallonFlavour

GALLON_STANDARD_KEY = "imperial_gallon_standard"


async def resolve_gallon_flavour(db: AsyncSession) -> GallonFlavour:
    """Return the configured gallon flavour, defaulting to US.

    Anything other than a case-insensitive "uk" resolves to "us", so a missing
    row, an empty value, or a typo degrades to the historical default rather
    than raising.
    """
    row = (
        await db.execute(select(Setting).where(Setting.key == GALLON_STANDARD_KEY))
    ).scalar_one_or_none()
    if row is not None and (row.value or "").strip().lower() == "uk":
        return "uk"
    return "us"
