# Units

A map of where units live in MyGarage, with pointers to the code that owns each
decision. It is deliberately short: an earlier version of this file ran to 434
lines and described a different application (Imperial storage, a `mileage`
column, a backend with no conversion logic), and a public repo whose docs
disagree with its code costs a contributor more than one with no docs at all.
**When this file and the code disagree, the code is right. Say so in a PR.**

## Storage is metric-canonical

Every unit-bearing column holds an SI value. Nothing in the database is
Imperial, and there is no per-user storage format.

| Quantity | Stored as | A real column |
|---|---|---|
| Distance | kilometres | `fuel_records.odometer_km` `Numeric(10,2)` |
| Speed | km/h | `fuel_records.obc_avg_speed_kmh` `Numeric(5,1)` |
| Volume | litres | `fuel_records.liters` `Numeric(9,3)` |
| Consumption | L/100km | `fuel_records.obc_l_per_100km` `Numeric(5,2)` |
| Mass | kilograms | `fuel_records.tank_size_kg` `Numeric(6,2)` |
| Pressure | kPa | `tires.pressure_kpa` `Numeric(7,2)` |
| Temperature | °C | `fuel_records.outside_temp_c` `Numeric(4,1)` |
| Length | metres | `vehicles.length_m` `Numeric(5,2)` |
| Tread | millimetres | `tires.tread_depth_mm` `Numeric(5,2)` |
| Torque | Nm | none yet: a display preference with nothing stored |

The column NAME carries the unit, which is the point: a column called
`odometer_km` cannot quietly come to mean miles. Engine hours
(`fuel_records.engine_hours`) are dimensionless and have no adapter.

Torque is the exception and worth knowing about before you go looking: the
`UnitSet` carries a torque preference and `UNIT_ADAPTERS` carries `nm` and
`lbft`, but no column stores a torque today. The preference is real and the
storage is not yet.

Migration `053_metric_canonical_units.py` performed the inversion in place and
is `FATAL = True`. There is no rollback path.

## Units are resolved per QUANTITY, not per system

A user does not have "a unit system". They have eleven stored choices, which
resolve into a `UnitSet`: ten quantities plus `secondary_gallon`, the flavour a
gallon takes when the primary unit does not state one.

- Vocabulary and presets: `backend/app/constants/units.py`
- Resolution (preset plus per-column overrides): `backend/app/utils/unit_resolution.py`
- Stored on `users`: `unit_preference`, `show_both_units`, and eleven nullable
  override columns (`unit_distance`, `unit_volume`, ..., `secondary_gallon`).
  NULL means "no override", never "derive from the preset".
- Instance-wide default for clients with no account: the `default_unit_prefs`
  setting, parsed by `backend/app/utils/default_unit_prefs.py`.
- A client with no account keeps its own set in one `unit_prefs` localStorage
  key (`frontend/src/utils/unitPrefsStore.ts`), which replaced three legacy
  keys. It holds THREE states, not two: no units, units derived for this
  session by migrating the legacy keys, and units the client actually chose.
  Only a chosen set is persisted. Persisting a derived one freezes the gallon
  flavour guessed at module load, before `/settings/public` resolves, and
  every later path is guarded on the key being absent, so nothing heals it.

One route writes a preference: `PUT /auth/me/units`, schema
`UnitPreferenceUpdate` in `app/schemas/user.py`. A preset writes eleven
explicit NULLs and `custom` writes all eleven values, in one transaction;
there is no partial custom. `unit_preference` is deliberately absent from
`UserSelfUpdate` and `AdminUserUpdate`, because those routes guard every field
with `if ... is not None` and so cannot express "clear this column": a preset
written through one of them would leave the override columns masking it.
`PUT /auth/me` rejects the key with 422 (`extra="forbid"`) and
`PUT /auth/users/{id}` ignores it, because forbidding extras there would
change the rejection behaviour of every other admin field at the same time.

The controls are `frontend/src/components/settings/UnitSetEditor.tsx`: the
Imperial / Metric / Custom buttons plus the eleven selects, holding no state and
performing no request. `UnitPreferencesCard.tsx` writes this client's units with
it and `InstanceUnitDefaultsCard.tsx` writes `default_unit_prefs` with the same
controls. Choosing a preset CLEARS overrides, so the editor confirms first, and
the confirmation is in the editor rather than in either writer.

So litres with miles is a real, supported account, and **any code that collapses
the set into one binary `imperial | metric` answer is a defect**. The frontend's
`useUnitPreference().system` still exposes such a collapse, derived from VOLUME;
it is being removed, and the remaining call sites are the work list printed by
`bun run validate:units -- --report`.

## Conversion happens at the boundary, on BOTH sides

Both halves of the app convert, and they mirror each other module for module.

| Layer | Backend | Frontend |
|---|---|---|
| Conversion (numbers only) | `app/utils/unit_adapters.py` | `src/utils/unitAdapters.ts` |
| Show-both pairing | `app/utils/unit_counterparts.py` | (same file) |
| Composition (strings) | `app/utils/unit_formatting.py` | `src/utils/unitFormat.ts` |
| Derived rates | `app/utils/unit_derived.py` | (in `unitFormat.ts`) |
| Per-render context | `app/utils/render_context.py` | `useUnitFormat()` |

The conversion layer returns numbers and never a string. The composition layer
returns strings and does no arithmetic ON A SINGLE QUANTITY: it asks an adapter.
The one place it computes is a DERIVED rate, where two adapters have to be
combined and there is no single adapter to ask (`formatVolumePerDistance`
multiplies a converted volume by the distance adapter's own factor). Keeping the
layers apart is what lets a chart, a form field, a CSV column and a PDF share one
conversion.

The backend converts for everything it renders itself: PDF reports
(`app/utils/pdf_*.py`), notifications
(`app/services/notifications/dispatcher.py`), scheduled jobs
(`app/tasks/scheduled.py`) and the report CSVs. Whose units it uses depends on
who asked: a request-driven render takes the caller's, a scheduled job takes the
vehicle owner's. `render_context.py` owns that choice.

CSV import and export are their own contract: a v6 header names its own unit
with a vocabulary token (`Odometer (mi)`, `Volume (gal_uk)`), so a file is
readable without knowing who wrote it. See `app/utils/csv_units.py`.

## Reading a value in a component

```tsx
const u = useUnitFormat()

<p>{u.distance.format(record.odometer_km)}</p>        // honours show-both
<p>{u.distance.formatPrimary(record.odometer_km)}</p> // one unit, never a counterpart
<Field label={t('common:mileage')} unit={u.distance.label}>
```

`format` appends the counterpart when the reader has show-both on;
`formatPrimary` never does. Show-both is a preference about a reading, not about
every reading, so a chart tooltip or a dense table cell picks `formatPrimary`.

A derived quantity composes two units and is a module function rather than a
member of `u`, because a suffix has to be applied to each representation
independently (`"3.20 L/hr (0.85 gal/hr)"`, never `"3.20 L (0.85 gal)/hr"`):

```ts
formatFuelRate(units, record.l_per_hr, showBoth)   // volume per engine hour
formatVolumePerDistance(units, litersPer1000Km)    // DEF and propane rates
```

## Entering and storing a value

Display and entry use the SAME unit, so a form must not re-convert a field the
user never touched. Round-tripping 7.50 mm through a `/32 in` field yields
7.14375 mm, which silently rewrites a value the user only looked at.

```ts
const origin = seedUnitField(record.odometer_km, u.distance)   // populate
const canonical = canonicalFromUnitField(typed, origin, u.distance)  // read back
```

`canonicalFromUnitField` returns the ORIGINAL canonical value when the field
still reads what it was seeded with, compared numerically rather than as
characters. Every path into a form (add, edit, a receipt draft, a suggestion)
has to go through both, or the one that does not becomes the corrupting one.
Both are in `frontend/src/utils/unitFormat.ts`.

## The gate

`frontend/scripts/validate-units.ts` fails a build on ANY unit-system branch it
can see. It reports five kinds, each with its own remedy in the failure message.

It used to be a baseline gate, where known findings were recorded in
`units.baseline.json` and the baseline could only shrink. Plan 3b task 8 retired
that: the baseline file is `[]`, the gate is CLEAN-ROOM, and `--update` refuses
to rewrite it and exits 2. There is nowhere to record a new finding, which is
the point. Fix it, or mark the line:

```
// units-exempt(<kind>): <reason>
```

The kind is required. It silences that leg on that line and leaves every other
kind reportable, which the bare form did not. On a binary DECLARATION the kind
is `binary-conversion` or `formatter-binary`, and that one line removes the
declaration from the gate's vocabulary, and with it every reference to it in
every module; the gate counts what each mechanism hides on every run.

```
bun run validate:units                   # the gate
bun run validate:units -- --report       # every finding, by file
bun run validate:units -- --derived      # the binary API surface it derives
bun run validate:units -- --suppressions # everything it is deliberately silent about
```

What the gate prints is "no unsuppressed expression matches these detectors",
which is smaller than "no unit defect exists" and deliberately so. Two shapes
have no lexical form for any detector to match: a resolved-set helper that
collapses INTERNALLY, and a forced-unit template. Those, and anything else it
cannot see mechanically, are recorded in `frontend/scripts/units.manifest.json`,
a reviewed per-file snapshot with its own checker.

## Gallon flavour

US and UK gallons differ by 20%, so `gal` alone is not a unit. The account's own
`secondary_gallon` decides which one a litre-primary reader is paired with (D4b);
`gal_us` and `gal_uk` state their own flavour and win outright.

A legacy instance-wide `imperial_gallon_standard` setting still exists, with no
control of its own and nothing in the browser reading it. It is read only when
the `default_unit_prefs` row is created or recreated at boot
(`default_unit_prefs_for_instance`), so changing it afterwards does not
retroactively move anything. It is kept deliberately, as the seed and fallback
that row is rebuilt from if it is ever deleted, and for nothing else. Do not
reach for it in new code; resolve the account's `secondary_gallon`, which the
Custom controls set per account.

| Flavour | Litres | MPG factor |
|---|---|---|
| US | 3.78541 | 235.214 |
| UK | 4.54609 | 282.481 |

## Adding a unit

1. Add the token to the quantity's `Literal` in `app/constants/units.py` and to
   the generated frontend types (`bun run generate:api`).
2. Add its adapter to `ADAPTERS` in `app/utils/unit_adapters.py` and to
   `UNIT_ADAPTERS` in `src/utils/unitAdapters.ts`, with the same label and
   precision. Nothing asserts those two tables against each other across the
   language boundary, so this step is a manual mirror; each side's own tests
   pin its half.
3. Give it a counterpart in both `unit_counterparts` modules, or decide it has
   none.
4. Add a migration if a stored `default_unit_prefs` row changes shape.

A new QUANTITY is more work: `UNIT_QUANTITIES` in `src/types/units.ts` carries a
compile-time completeness proof, so the type errors will find the call sites for
you.
