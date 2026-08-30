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
     - (none left)

   MIGRATED (phase 2b, task 3): routes/export.py's CSV export values and
   marker. `build_csv` now takes one resolved `UnitSet`
   (`resolve_export_units`) and derives both the header tokens and the
   `unit_system` marker from it, so an `?units=imperial` export is the
   imperial PRESET (US gallons, marker `imperial`) whatever this setting
   says, and a UK account's own export carries `Volume (gal_uk)` under
   marker `custom`. Emitting `imperial_uk` has stopped; accepting it on
   import has not.

   MIGRATED (phase 2a, task 6): services/notifications/dispatcher.py's DEF-low
   volume no longer calls this module. It takes a `RenderContext` from its
   caller (the scheduled job resolves the vehicle owner's) and picks its gallon
   flavour by D4b precedence in `unit_formatting.format_forced_volume_pair`.

   MIGRATED (phase 2a, task 7): services/widget_aggregation.py's v1/v2 MPG
   fields no longer call this module either. Both widget route modules resolve
   the key owner's `UnitSet` and pass it into the aggregation, which picks the
   MPG flavour by the same D4b precedence via
   `unit_counterparts.forced_mpg_adapter`. The one remaining entry above is
   still instance-wide.

2. FILE OR REQUEST MARKER -- the flavour travels with the data, never from a
   preference:
     - utils/csv_units.py `build_csv_unit_context`     reads the file's own
       header tokens and `unit_system` marker (CSV import path); already
       explicit, already correct, do not change. MOVED here in phase 2b
       (task 2) from `routes/import_data.py`'s `_row_gallons_to_liters`,
       which schema v6 replaced with a per-column, per-file resolution; the
       property that made it correct -- the unit travels with the data, never
       from a preference -- is unchanged and is now asserted behaviourally by
       a cross-user import test.
     - routes/export.py `?units=` query parameter      caller's explicit
       request, now resolved to a whole `UnitSet` rather than a gallon
       flavour (phase 2b, task 3)
     - services/notifications/dispatcher.py `notify_livelink_threshold_alert`
       (CLASSIFIED phase 2a, after the whole-branch review found it
       unclassified). It renders `f"{value:.1f}{unit_str} vs threshold
       {threshold_value:.1f}{unit_str}"` where `unit` is the DEVICE's own
       `LiveLinkParameter.unit` (`# From config.{key}.unit`), so the unit
       travels with the datum: class 2, not a preference consumer, and it
       takes no `RenderContext`.

       BUT it is not unit-free, and a later phase does have work here: a
       COOLANT_TMP alert reaches a Fahrenheit-preferring user in whatever
       the WiCAN reported. Converting it is a data-model change rather than
       a rendering change, for three reasons. `VehicleTelemetry.value` is a
       bare `Float` stored exactly as received, with no canonicalization
       (`utils/autopid_normalizer.py` canonicalizes the KEY only, never the
       unit). `LiveLinkParameter.warning_min`/`warning_max` are user-entered
       in that same device unit, so converting the message without
       converting the threshold entry would state a breach against a
       threshold the user never set. And `LiveLinkParameter.unit` is free
       text (`String(20)`) with no mapping into `UnitSet`'s 24-token
       vocabulary. Whoever picks this up must land that mapping and decide
       the storage question first.

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
       US whenever `is_legacy_v2`. Same reasoning as `csv_units` above --
       pre-v3 files predate the UK gallon option entirely -- but
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
