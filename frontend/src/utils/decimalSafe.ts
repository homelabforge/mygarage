/**
 * Canonical-write helpers for form submit paths.
 *
 * ★ EVERY EXPORT HERE TAKES THE RESOLVED `UnitSet`, NEVER A BINARY `UnitSystem`,
 * and that is an invariant rather than a coincidence. Three helpers that broke
 * it were deleted in phase 3b task 5 under ruling R8: `toCanonicalKm`,
 * `toCanonicalKg` and `toCanonicalMeters` each took a `UnitSystem` collapsed
 * from the user's VOLUME choice (`useUnitPreference.ts:systemFor`) and wrote a
 * canonical value off it, so a `{volume:'L', distance:'mi'}` user's 500 miles
 * stored as 500 km instead of 804.67. Nothing at such a call site named a unit,
 * so neither of the units gate's original legs could see the function writing
 * the wrong number, which is why R8 chose deletion over detection: the bad call
 * is now inexpressible rather than merely reported.
 *
 * Writers use `seedUnitField` / `canonicalFromUnitField` from
 * `utils/unitFormat.ts`, which preserve the unit the value was entered in.
 * `utils/__tests__/unitsBinaryApiSurface.test.ts` fails on the DECLARATION if a
 * binary helper is ever added back here.
 *
 * ★ AND SINCE PLAN 3b TASK 7, NO EXPORT HERE CONVERTS A DISPLAY VALUE STRAIGHT
 * TO CANONICAL EITHER. That is a second defect class on the same file and it is
 * closed the same way. `toCanonicalLiters(value, units)` and
 * `priceToCanonical(value, units, basis)` were each correct for an EDITED field
 * and wrong for an untouched one: the field had been seeded with a rounded
 * display, and reconverting that rounding moved a stored value nobody edited.
 * `toCanonicalLiters` is gone (volume is a quantity and goes through the
 * protocol; `toLitersWirePrecision` is the wire-contract half it could not
 * supply) and `priceToCanonical` is module-private behind `seedPriceField` /
 * `canonicalFromPriceField`, the price mirror of that protocol. Price needs its
 * own pair rather than the quantity one because price is not a quantity: its
 * display MULTIPLIES by the denominator factor where a volume adapter divides,
 * and its denominator can change under the field while the number does not.
 */
import { unitFieldUnchanged, type UnitFieldOrigin } from './unitFormat'
import { UnitConverter } from './units'
import type { UnitSet } from '@/types/units'

/**
 * Significant digits every canonical value carries onto the wire.
 *
 * Matches `utils/unitAdapters.ts`: `number` is IEEE 754, so `6 / 4.54609`
 * evaluates to a value whose tail is noise, and posting it stores a number one
 * ulp away from the conversion's own answer.
 */
const CANONICAL_SIGNIFICANT_DIGITS = 12

/**
 * Decimal places a canonical LITRE value is rounded to before it is posted.
 *
 * ★ The wire-precision rule this task settled, applied here: a canonical write
 * is rounded ONLY where the API contract declares a precision, and then to
 * exactly the precision it declares. `liters` and `propane_liters` carry
 * `decimal_places=3` in `app/schemas/fuel.py` and `app/schemas/def_record.py`,
 * and pydantic REJECTS a fourth with a 422 rather than rounding it, so this
 * rounding is the contract's, not one the client invented. Everything else
 * this file writes (`price_per_unit`) declares no precision and is therefore
 * posted exactly, the same way `odometer_km`, `tread_depth_mm` and
 * `pressure_kpa` have been since the adapter landed.
 *
 * The old 2-decimal rounding was the client's own, tighter than the contract,
 * and it lost a digit of a gallon entry on every save.
 */
const LITERS_WIRE_DECIMALS = 3

/**
 * Decimal places a price is READ and ENTERED at.
 *
 * A display decision, not a storage one: it is what the price field has always
 * shown, and it is the fixed point that makes reopening a record and saving it
 * untouched a no-op.
 */
const PRICE_DISPLAY_DECIMALS = 3

/**
 * Normalise a converted value for the wire.
 *
 * @param value The raw arithmetic result.
 * @returns The value at 12 significant digits.
 */
function toWirePrecision(value: number): number {
  return Number(value.toPrecision(CANONICAL_SIGNIFICANT_DIGITS))
}

/**
 * Read a numeric value out of a form field, tolerating everything one can hold.
 *
 * A field registered with `registerDecimal` holds a number, `undefined`, or
 * the `INVALID_NUMBER` sentinel for text that does not parse. That sentinel
 * is a Symbol, and Symbols throw on every implicit coercion: both
 * `parseFloat(sym)` and `isNaN(sym)` raise a TypeError. So the obvious
 * `typeof v === 'number' ? v : parseFloat(v)` blows up the moment someone
 * types "abc" into a field that feeds a calculation. Returns undefined for
 * anything that is not a usable number, which callers read as "no value yet".
 */
export function readNumber(value: unknown): number | undefined {
  if (typeof value === 'number') return Number.isFinite(value) ? value : undefined
  if (typeof value === 'string') {
    const parsed = parseFloat(value)
    return Number.isNaN(parsed) ? undefined : parsed
  }
  return undefined
}

/**
 * Round a canonical litre value to the precision the API declares.
 *
 * ★ WHAT THIS REPLACED, because the replacement is the point of plan 3b task 7
 * rather than a rename. `toCanonicalLiters(value, units)` took the value a
 * volume FIELD currently held and converted it straight to canonical litres. On
 * an edit that is right; on a save the user never made an edit in it is the
 * entry-grid shift, because the field had been seeded with a value rounded to
 * the volume unit's two decimals and the submit reconverted that rounding.
 * Measured across 27 value and unit-set combinations, 13 moved, from 0.0006% at
 * a 10,000-litre fill to 100% at the wire's smallest representable 0.001 L.
 *
 * Volume now goes through the origin-preserving protocol in `unitFormat.ts`
 * exactly as distance, mass, temperature and the OBC fields already do:
 * `seedUnitField(canonical, u.volume)` on the way in and
 * `canonicalFromUnitField(typed, origin, u.volume)` on the way out. What that
 * protocol cannot supply is this rounding, and it should not: `liters` and
 * `propane_liters` carry `decimal_places=3` in `app/schemas/fuel.py` and
 * `app/schemas/def_record.py`, and pydantic REJECTS a fourth with a 422 rather
 * than rounding it, so the wire contract is a separate step from the unit
 * conversion and is named separately here. Deleting the old helper rather than
 * leaving it beside the protocol is the call task 5 made one class over: the
 * reconverting shape is now inexpressible instead of merely discouraged.
 *
 * The old 2-decimal rounding was the client's own, tighter than the contract,
 * and it lost a digit of a gallon entry on every save.
 *
 * @param liters A canonical litre value, from the protocol or from arithmetic.
 * @returns The value at the API's declared precision, or null when absent.
 */
export function toLitersWirePrecision(liters: number | null | undefined): number | null {
  if (liters == null || isNaN(liters)) return null
  return parseFloat(toWirePrecision(liters).toFixed(LITERS_WIRE_DECIMALS))
}

export type PriceBasis = 'per_volume' | 'per_weight' | 'per_kwh' | 'per_tank'

/**
 * How many canonical units one of the client's typed units contains, for the
 * denominator a price basis names.
 *
 * ★ This replaces a hardcoded `LITERS_PER_GALLON = 3.78541` that sat under a
 * comment claiming the factors were "mirrored from UnitConverter". They were,
 * once; `units.ts` made its gallon dynamic when the UK standard shipped in
 * v3.1.0 and this copy did not follow, so a UK user's price was 20.1 percent
 * high and the read-back used the same wrong factor, which is why nothing on
 * screen disagreed. Reading the denominator from the client's own resolved set
 * fixes both the stale constant and the instance-versus-user question at once.
 *
 * A basis with no unit in its denominator (`per_kwh`, `per_tank`, an unknown
 * string) returns null, and the caller passes the value through untouched.
 *
 * @param units The client's resolved unit set.
 * @param basis The record's price basis.
 * @returns Canonical units per typed unit, or null when nothing converts.
 */
function canonicalPerTypedUnit(
  units: UnitSet,
  basis: PriceBasis | string | null | undefined,
): number | null {
  if (basis === 'per_volume') return UnitConverter.LITERS_PER_VOLUME_UNIT[units.volume]
  if (basis === 'per_weight') return UnitConverter.KG_PER_MASS_UNIT[units.mass]
  return null
}

/**
 * Convert a canonical SI price (per liter / per kg) into the user's display
 * unit, as the client's resolved set names it. per_kwh and per_tank are
 * universal and pass through unchanged.
 *
 * @param value The stored canonical price, as a number or an API string.
 * @param units The client's resolved unit set.
 * @param basis The record's price basis.
 * @returns The price per displayed unit, or null when there is no value.
 */
export function priceToDisplay(
  value: number | string | null | undefined,
  units: UnitSet,
  basis: PriceBasis | string | null | undefined,
): number | null {
  if (value == null) return null
  const num = typeof value === 'string' ? parseFloat(value) : value
  if (isNaN(num)) return null
  const factor = canonicalPerTypedUnit(units, basis)
  // A factor of 1 means the client's unit IS the canonical one, so there is
  // nothing to convert and nothing to re-round: rounding a stored litre price
  // here would rewrite it on a save the user never made an edit in.
  if (factor === null || factor === 1) return num
  return parseFloat((num * factor).toFixed(PRICE_DISPLAY_DECIMALS))
}

/**
 * Convert a user-entered display-unit price back into canonical SI ($/L,
 * $/kg). Inverse of priceToDisplay.
 *
 * ★ MODULE-PRIVATE SINCE PLAN 3b TASK 7, and that is the same call R8 made for
 * the three binary helpers rather than a visibility tidy-up. Applied to a value
 * a form field was SEEDED with, this reconverts a rounded display and moves a
 * price the user never edited: canonical `1.234567` comes back `1.23446742145`,
 * and 16 of 27 measured value and unit-set combinations moved. Every writer now
 * goes through `seedPriceField` / `canonicalFromPriceField` below, which hand an
 * untouched field its stored value back, so the reconverting call is no longer
 * reachable from outside this module.
 *
 * Posted exactly, at the wire's 12 significant digits: `price_per_unit`
 * declares no `decimal_places` in the API schema, so a client-side round would
 * be a second, invented authority on storage precision. See
 * `LITERS_WIRE_DECIMALS` for the rule. (The COLUMN is `Numeric(6, 3)`, so a
 * PostgreSQL instance rounds the tail off on arrival; that is the database's
 * contract to state, not the client's to anticipate.)
 *
 * @param value The price the user entered, per displayed unit.
 * @param units The client's resolved unit set.
 * @param basis The record's price basis.
 * @returns The canonical price, or null when there is no value.
 */
function priceToCanonical(
  value: number | null | undefined,
  units: UnitSet,
  basis: PriceBasis | string | null | undefined,
): number | null {
  if (value == null || isNaN(value)) return null
  const factor = canonicalPerTypedUnit(units, basis)
  if (factor === null || factor === 1) return value
  return toWirePrecision(value / factor)
}

/**
 * A price field's canonical origin: what it held, how that read, and as WHAT.
 *
 * ★ THE THIRD FIELD IS THE WHOLE REASON PRICE HAS ITS OWN PAIR. A quantity's
 * origin is complete with a canonical value and the string it produced, because
 * the unit never changes underneath the field. A price's denominator does: the
 * fuel form's `price_basis` is a `<select>` the user can move from `per_volume`
 * to `per_weight` without touching the number, and the propane form seeds a
 * legacy `per_tank` record's raw value and deliberately re-reads it as
 * `per_volume` on save. In both cases the CHARACTERS are unchanged and the
 * QUANTITY is not, so an origin that only remembered the number would hand back
 * a $/gal figure relabelled $/lb, or store a per-tank total as a per-litre
 * price. Comparing the basis is what makes "untouched" mean untouched.
 */
export interface PriceFieldOrigin extends UnitFieldOrigin {
  /** The basis the seeded value was read under, `null` for none. */
  basis: PriceBasis | string | null
}

/**
 * Populate a price field, remembering the canonical value and basis behind it.
 *
 * The price mirror of `seedUnitField`. It cannot BE `seedUnitField`: that takes
 * a `QuantityFormat`, and price is not a quantity. A price display MULTIPLIES
 * by the denominator factor where a volume adapter divides, so canonical
 * $1.20/L pushed through a UK-gallon volume formatter renders `0.26` where
 * price semantics want about `5.46/gal`.
 *
 * The display string is `priceToDisplay`'s own answer, unchanged: that function
 * already applies the field's three decimals wherever it converts, and a litre
 * set's price IS canonical and is shown exactly as stored. Re-rounding here
 * would be a second display authority disagreeing with the list column beside
 * it, which reads through the same function.
 *
 * ★ SO A METRIC ROW IS ASYMMETRIC, AND THAT IS A CHOICE RATHER THAN AN
 * OVERSIGHT. In the same two-column entry grid, a metric VOLUME now shows two
 * decimals (the `L` adapter's precision, which every rendered volume in the app
 * uses) while a metric PRICE keeps whatever precision it was stored with. The
 * two are not the same kind of number: volume has an adapter and a rendered
 * counterpart everywhere else on the screen to agree with, and price has
 * neither, so rounding it here would round it ONLY here. The stored value
 * survives on both sides through the origin, which is the property that
 * matters; the display precision is the thing that differs.
 *
 * @param value The stored canonical price, as a number or an API string.
 * @param units The client's resolved unit set.
 * @param basis The basis the stored value is quoted under.
 * @returns The field's display string, its canonical origin and its basis.
 */
export function seedPriceField(
  value: number | string | null | undefined,
  units: UnitSet,
  basis: PriceBasis | string | null | undefined,
): PriceFieldOrigin {
  const canonical = readNumber(value) ?? null
  const display = priceToDisplay(canonical, units, basis)
  return { canonical, display: display === null ? '' : String(display), basis: basis ?? null }
}

/**
 * Read a price field back into canonical storage, without moving an untouched one.
 *
 * The price mirror of `canonicalFromUnitField`, sharing its `unitFieldUnchanged`
 * predicate so there is one answer to "did the user touch this" rather than two
 * that can drift. What it adds is the basis comparison: a field whose number is
 * unchanged but whose DENOMINATOR moved is an edit, because the same characters
 * now mean a different quantity.
 *
 * @param typed What the input currently holds.
 * @param origin What `seedPriceField` recorded for this field.
 * @param units The client's resolved unit set.
 * @param basis The basis the submitted value is quoted under.
 * @returns The canonical price to store, or null when the field is empty or
 *   holds something that is not a number.
 */
export function canonicalFromPriceField(
  typed: string,
  origin: PriceFieldOrigin,
  units: UnitSet,
  basis: PriceBasis | string | null | undefined,
): number | null {
  if ((basis ?? null) === origin.basis && unitFieldUnchanged(typed, origin)) return origin.canonical
  if (typed.trim() === '') return null
  return priceToCanonical(Number(typed), units, basis)
}
