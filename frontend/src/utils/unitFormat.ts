/**
 * Composition layer: turn a canonical number into the string a user reads, and
 * into the string a form field holds.
 *
 * The frontend mirror of `backend/app/utils/unit_formatting.py`. It sits on top
 * of the conversion layer (`utils/unitAdapters.ts`) and is the first place the
 * show-both grammar (a primary representation, optionally followed by its
 * counterpart in parentheses) is assembled. The adapters are deliberately
 * primitive so that composition lives here instead of leaking into them.
 *
 * **Everything user-visible here returns a `string`; every number that reaches
 * it has already been converted by the layer below.** `toDisplay` and
 * `toCanonical` are re-exposed per quantity purely as delegation, so a call
 * site holds one object rather than an adapter and a formatter; they contain no
 * arithmetic of their own.
 *
 * `format` short-circuits on null before the counterpart is considered, exactly
 * as the backend does: naively formatting both sides of an absent value would
 * render `"N/A (N/A)"`. The check is the primary adapter's own `toDisplay`, not
 * a string comparison, so a coincidentally N/A-shaped label cannot fool it.
 *
 * ★ `toInputValue` and the two `UnitField` helpers are the ENTRY and STORAGE
 * boundary, and they exist because a display unit that only formats corrupts
 * data. Binding decision D2 requires one unit for entry and display, so once a
 * tread field reads `9/32 in` the input means thirty-seconds too. The trap is
 * the round trip: 7.50 mm shows as 9, and 9 converts back to 7.14375 mm, so a
 * user who opens a form, edits an unrelated field and saves would silently
 * rewrite a value they never touched. `seedUnitField` records the canonical
 * value each field was populated from, and `canonicalFromUnitField` gives that
 * value straight back when the field still reads what it was seeded with. Every
 * form path (add, edit, and any separate reading path) must go through both, or
 * the one that does not becomes the corrupting one.
 *
 * ★ PRICE OBEYS THE SAME PROTOCOL AND CANNOT USE THESE TWO FUNCTIONS, which is
 * why `unitFieldUnchanged` is exported rather than inlined. Both helpers here
 * require a `QuantityFormat`, and price is not a quantity: its display
 * MULTIPLIES by the denominator factor where a volume adapter divides, so
 * canonical $1.20/L pushed through a UK-gallon volume formatter renders `0.26`
 * where price semantics want about `5.46/gal`. Its pair lives beside the price
 * arithmetic in `utils/decimalSafe.ts` (`seedPriceField` /
 * `canonicalFromPriceField`) and shares this module's untouched predicate, so
 * the one decision both make has one implementation.
 *
 * There are no translated strings in this module. Unit labels are symbols, not
 * prose, and `"N/A"` matches what `UnitFormatter` has always rendered; adding
 * `i18next.t()` here would need namespace-qualified keys, since this is not a
 * component and has no `useTranslation`.
 */

import { getActiveLocale } from '@/constants/i18n'
import { UNIT_QUANTITIES, type UnitQuantity, type UnitSet } from '@/types/units'
import { adapterFor, counterpartFor, type UnitAdapter, type UnitToken } from './unitAdapters'

/**
 * What `format` renders when there is no value to render.
 *
 * Exported because a value beside a formatted one has to spell absence the same
 * way: the fuel form's OBC preview renders two quantities through `format` and
 * a trip duration in seconds, which is not a quantity and has no formatter. A
 * literal there would silently disagree the day this constant moves, and the
 * module docstring above deliberately leaves that door open.
 */
export const NOT_AVAILABLE = 'N/A'

/** One quantity's units, resolved for a particular client. */
export interface QuantityFormat {
  /** The resolved token, e.g. `'in32'`. */
  readonly unit: UnitToken
  /** The unit's display label, e.g. `'/32 in'`. */
  readonly label: string
  /** Decimal places this unit is read and entered at. */
  readonly precision: number
  /** The `step` an `<input type="number">` in this unit should carry. */
  readonly step: string
  /** Canonical to this unit. Exact; the conversion layer's answer, unrounded. */
  toDisplay(canonical: number | null | undefined): number | null
  /** This unit to canonical. Exact; the conversion layer's answer, unrounded. */
  toCanonical(typed: number | null | undefined): number | null
  /** Canonical to the ungrouped string an `<input type="number">` accepts. */
  toInputValue(canonical: number | null | undefined): string
  /**
   * Canonical to the grouped number a reader sees, with NO label.
   *
   * `format` is the whole string; this is its numeric half, for a call site
   * that renders the label separately (LiveLink's gauges set the unit in a
   * smaller type size). An absent value is `''` rather than `'N/A'`, matching
   * `toInputValue`: a caller composing its own label supplies its own absent
   * marker, and `'N/A'` beside a unit label would read as a value.
   */
  toDisplayText(canonical: number | null | undefined): string
  /**
   * Canonical to a labelled string in THIS unit only, never the counterpart.
   *
   * ★ It exists because the capability would otherwise have been silently
   * dropped in the migration. The binary `formatDistance(km, system, showBoth)`
   * took the counterpart as an ARGUMENT, and 13 of its 21 read sites declined
   * it: 9 passed `false` outright and 4 left the argument off, which defaulted
   * to the same thing. They are chart tooltips, dense table cells and inline
   * spans, where a parenthesised second unit is noise rather than information.
   * `format` reads show-both off the resolved set, so moving those sites onto
   * it would start rendering a counterpart nobody asked for AT THAT SITE.
   * Show-both is a preference about a reading, not about every reading.
   *
   * (An earlier revision of this comment said "eleven of the 27 sites", which
   * was wrong twice: 27 counts the whole binary-distance surface, and 6 of
   * those are `getDistanceUnit` / `kmToMiles` sites with no `showBoth`
   * parameter to decline.)
   */
  formatPrimary(canonical: number | null | undefined): string
  /**
   * Canonical to a labelled string, with the counterpart when show-both is on.
   *
   * ★ The short-circuit below is about an ABSENT PRIMARY, not about a complete
   * pair, so a present primary whose COUNTERPART is undefined renders
   * `'0.00 L/100km (N/A)'`. That is reachable exactly once per quantity: a
   * linear primary at zero paired with a reciprocal counterpart. It is the
   * honest reading (the primary really is zero and the counterpart really has
   * no finite value) and `unitFormatFuelRate.test.ts` pins it, because an
   * unasserted boundary is one somebody later "fixes" into `'N/A'` and loses a
   * true number.
   */
  format(canonical: number | null | undefined): string
}

/** Every quantity, resolved for a particular client. */
export type UnitFormat = Readonly<Record<UnitQuantity, QuantityFormat>>

/**
 * A unit-bearing form field's canonical origin.
 *
 * `display` is the string `seedUnitField` produced, kept so that "the user did
 * not touch this" is a comparison rather than a guess. Re-typing the same
 * displayed value counts as untouched, which is correct: the displayed quantity
 * did not change, so neither should the stored one.
 */
export interface UnitFieldOrigin {
  /** The canonical value the field was populated from, if any. */
  canonical: number | null
  /** The string that canonical value produced, in the client's unit. */
  display: string
}

/**
 * Render a number at a fixed precision, grouped for the active locale.
 *
 * Exported because a value OUTSIDE the unit system still has to be rendered the
 * same way: LiveLink's RPM, voltage and percentage gauges carry a precision but
 * no adapter, and formatting them locally is how `telemetryUnits.ts` grew a
 * second implementation of this function.
 *
 * @param value The already-converted display value.
 * @param precision Decimal places.
 * @returns The grouped string, e.g. `'1,000'`.
 */
export function formatAtPrecision(value: number, precision: number): string {
  return new Intl.NumberFormat(getActiveLocale(), {
    minimumFractionDigits: precision,
    maximumFractionDigits: precision,
  }).format(value)
}

/**
 * Render one adapter's view of a canonical value, label included.
 *
 * The separating space is suppressed for a label that starts with `/`, so tread
 * reads `'9/32 in'` rather than `'9 /32 in'`.
 *
 * @param adapter The adapter to render through.
 * @param canonical The canonical value.
 * @returns The labelled string, or `'N/A'` when there is nothing to render.
 */
function render(adapter: UnitAdapter, canonical: number | null | undefined): string {
  const display = adapter.toDisplay(canonical)
  if (display === null) return NOT_AVAILABLE
  const number = formatAtPrecision(display, adapter.precision)
  return adapter.label.startsWith('/') ? `${number}${adapter.label}` : `${number} ${adapter.label}`
}

/**
 * Build one quantity's formatter.
 *
 * @param units The client's resolved unit set.
 * @param quantity Which quantity to build.
 * @param showBoth Whether to append the counterpart representation.
 * @returns The quantity's formatter.
 */
function quantityFormat(units: UnitSet, quantity: UnitQuantity, showBoth: boolean): QuantityFormat {
  return formatForAdapter(adapterFor(units, quantity), counterpartFor(units, quantity), showBoth)
}

/**
 * Build a formatter around an adapter chosen by the caller.
 *
 * Exists for the one quantity the resolved vocabulary cannot name: engine oil
 * capacity is read in quarts wherever fuel is read in gallons, and `UnitSet`
 * has no quart token (see `utils/oilCapacityUnit.ts`). Exported so that
 * quantity gets the SAME surface as every table-driven one, rather than a
 * second hand-written `QuantityFormat` free to drift from this one.
 *
 * @param adapter The unit to read and write in.
 * @param counterpart The show-both companion, or null when there is none.
 * @param showBoth Whether to append the counterpart representation.
 * @returns The formatter.
 */
export function formatForAdapter(
  adapter: UnitAdapter,
  counterpart: UnitAdapter | null,
  showBoth: boolean
): QuantityFormat {
  return {
    unit: adapter.unit,
    label: adapter.label,
    precision: adapter.precision,
    // 0 -> '1', 1 -> '0.1', 2 -> '0.01'. `toFixed` is for readability, not for
    // safety: no adapter in the table has a precision above 2, and `10 ** -1`
    // and `10 ** -2` both stringify exactly, so this line has no reachable case
    // where the two spellings differ. Replacing it with `String(...)` survives
    // mutation for that reason, which is a fact about the vocabulary rather
    // than a hole in the tests.
    step: adapter.precision === 0 ? '1' : (10 ** -adapter.precision).toFixed(adapter.precision),
    toDisplay: (canonical) => adapter.toDisplay(canonical),
    toCanonical: (typed) => adapter.toCanonical(typed),
    toInputValue(canonical) {
      const display = adapter.toDisplay(canonical)
      return display === null ? '' : display.toFixed(adapter.precision)
    },
    toDisplayText(canonical) {
      const display = adapter.toDisplay(canonical)
      return display === null ? '' : formatAtPrecision(display, adapter.precision)
    },
    formatPrimary(canonical) {
      return render(adapter, canonical)
    },
    format(canonical) {
      // Null short-circuits BEFORE the counterpart, or an absent value renders
      // as "N/A (N/A)".
      if (adapter.toDisplay(canonical) === null) return NOT_AVAILABLE
      const primary = render(adapter, canonical)
      if (!showBoth || counterpart === null) return primary
      return `${primary} (${render(counterpart, canonical)})`
    },
  }
}

/**
 * Build the formatters for a resolved unit set.
 *
 * The non-hook entry point: anything outside a component (an export, a chart
 * transform, a test) resolves its own set and calls this. `useUnitFormat()`
 * wraps it for components.
 *
 * @param units The client's resolved unit set.
 * @param showBoth Whether to append each counterpart representation.
 * @returns One formatter per quantity.
 */
export function makeUnitFormat(units: UnitSet, showBoth = false): UnitFormat {
  const out = {} as Record<UnitQuantity, QuantityFormat>
  for (const quantity of UNIT_QUANTITIES) {
    out[quantity] = quantityFormat(units, quantity, showBoth)
  }
  return out
}

/**
 * Every quantity's unit label for a resolved set, as one comma-separated list.
 *
 * ★ WHY THIS EXISTS, and it is a correctness fix rather than a convenience.
 * The settings screen used to choose between two fixed sentences, "Using
 * imperial units: gallons, miles, MPG, °F, PSI, lbs, lb-ft" and "Using metric
 * units: liters, kilometers, L/100km, °C, bar, kg, Nm", on the collapsed binary
 * system. That system is derived from VOLUME (spec D8), so a
 * `{volume:'L', distance:'mi', pressure:'psi'}` account was shown the metric
 * sentence and TOLD IT USES KILOMETRES AND BAR. It uses miles and PSI. Plan 3b
 * ruling R1: that is not explanatory copy needing an exemption, it is the app
 * stating something false about the reader's own settings, so the sentence is
 * composed from the resolved set instead of selected from two.
 *
 * ★ The labels come from `UNIT_ADAPTERS` through `adapterFor`, which is the same
 * table every rendered quantity in the app reads its label from. A second table
 * of prose unit names ("gallons", "kilometers") would be a fourth parallel unit
 * vocabulary of exactly the kind this workstream has been unpicking, and it
 * could drift from what the screens actually render. It also means the list
 * needs no translation: these are symbols, not prose, and the surrounding
 * sentence is the translated part.
 *
 * ★ It walks `UNIT_QUANTITIES` rather than a hand-picked list. The sentence it
 * replaced named seven of the ten quantities, and a list maintained by hand is
 * a floor: speed, length and tread were simply missing, so a user with imperial
 * tread and metric everything else read a description that could not mention
 * it. `UNIT_QUANTITIES` carries a compile-time completeness proof, so a
 * quantity added later appears here without anybody remembering to add it.
 *
 * @param units The client's resolved unit set.
 * @returns The ten labels, in `UNIT_QUANTITIES` order, e.g.
 *   `'mi, mph, ft, gal, MPG, PSI, °F, lb, lb-ft, /32 in'`.
 */
export function resolvedUnitSummary(units: UnitSet): string {
  return UNIT_QUANTITIES.map((quantity) => adapterFor(units, quantity).label).join(', ')
}

/**
 * How many of the reader's distance units a consumption rate is quoted over.
 *
 * Not a conversion factor: it is the denominator the DEF and propane cards have
 * always shown, and `volumePerDistanceLabel` spells it out beside the number.
 */
const VOLUME_PER_DISTANCE_OVER = 1000

/** Decimal places a volume-per-distance rate is read at. */
const VOLUME_PER_DISTANCE_PRECISION = 1

/**
 * Render a volume-per-distance rate in the reader's OWN two units.
 *
 * ★ IT TAKES BOTH HALVES FROM THE RESOLVED SET, and that is the whole change.
 * `UnitFormatter.formatVolumePerDistance` lived in `utils/units.ts` and derived
 * the DISTANCE half from `units.volume`: a litre set rendered per 1,000 km and
 * every other set rendered per 1,000 mi. So a `{volume:'L', distance:'mi'}`
 * account read a kilometre rate on the same DEF card whose odometer column read
 * miles, and neither answer the helper could give was right for it. Its own
 * comment promised "Distance migrates in 3b, per file, with its neighbours";
 * this is that migration, landed in the same change as those neighbours.
 *
 * ★ AND IT IS THE SHAPE THE UNITS GATE DELIBERATELY CANNOT SEE.
 * `formatVolume(units)` is correct and this was CALL-SITE IDENTICAL to it, so
 * no lexical rule separates them (`validate-units.ts` says so at length); it
 * was carried by `units.manifest.json` instead, which is reviewed rather than
 * matched. Nothing mechanical would have found it.
 *
 * ★ WHY IT MOVED FILES RATHER THAN GROWING A SECOND TABLE. `utils/units.ts`
 * cannot import `adapterFor`: `unitAdapters.ts` builds its table from
 * `UnitConverter` at module scope, so a runtime import back would form a cycle
 * (that file's `import type` comment states the hazard). Left there, the
 * distance half would have needed a `KM_PER_DISTANCE_UNIT` map beside
 * `LITERS_PER_VOLUME_UNIT`, a second dispatch of a decision the adapter table
 * already makes, and a second copy of a unit decision is the defect this
 * workstream keeps unpicking. Here both halves come from `adapterFor`, so there
 * is nothing to drift.
 *
 * @param units The client's resolved unit set.
 * @param litersPer1kKm The canonical rate, litres per 1,000 km.
 * @returns The rate in the set's own units, at one decimal, with NO label.
 */
export function formatVolumePerDistance(units: UnitSet, litersPer1kKm: number): string {
  const volume = adapterFor(units, 'volume').toDisplay(litersPer1kKm) ?? 0
  // Per 1,000 km to per 1,000 of the reader's own distance unit. One mile is
  // 1.60934 km, so the same volume covers that many fewer of them and the rate
  // rises by the same factor. The canonical length of one display unit is
  // exactly what the distance adapter's `toCanonical(1)` answers, so no factor
  // is spelled here.
  //
  // ★ THE `?? 1` THAT USED TO BE HERE WAS A GUARD NO TEST COULD KILL, and it
  // was worse than unkillable: `toCanonical` returns null only for an ABSENT or
  // NaN input, and `1` is neither, so the fallback could never fire, and if it
  // somehow did it would substitute a kilometre for a mile and report a wrong
  // number confidently. Replacing it with `?? 1` -> `as number` survived the
  // whole suite, which is this phase's own test for a predicate that should not
  // exist. The assertion says what is true instead of pretending to handle what
  // is not.
  const canonicalPerDistanceUnit = adapterFor(units, 'distance').toCanonical(1)!
  return formatAtPrecision(volume * canonicalPerDistanceUnit, VOLUME_PER_DISTANCE_PRECISION)
}

/**
 * The compound label a volume-per-distance rate is read under.
 *
 * Composed from the two adapters rather than selected from two fixed strings,
 * for the reason `resolvedUnitSummary` gives at length: a second table of unit
 * names is a parallel vocabulary that can disagree with what the screens
 * render. `getVolumePerDistanceLabel` was such a selection and could produce
 * only `'L/1,000 km'` or `'gal/1,000 mi'`; the two mixed spellings a custom
 * account can hold were not expressible at all.
 *
 * @param units The client's resolved unit set.
 * @returns e.g. `'gal/1,000 mi'`, `'L/1,000 km'`, or `'L/1,000 mi'`.
 */
export function volumePerDistanceLabel(units: UnitSet): string {
  const over = formatAtPrecision(VOLUME_PER_DISTANCE_OVER, 0)
  return `${adapterFor(units, 'volume').label}/${over} ${adapterFor(units, 'distance').label}`
}

/**
 * The dimensionless denominator a fuel rate is quoted over.
 *
 * Engine hours are outside the unit system entirely (backend ruling R6: they
 * have no adapter), so the suffix is held FIXED while the volume half flips.
 * It is a symbol rather than prose, like every other label in this module.
 */
const PER_HOUR = '/hr'

/**
 * Render an engine-hours fuel rate in the reader's own volume unit.
 *
 * ★ IT IS THE VOLUME QUANTITY, NOT A QUANTITY OF ITS OWN, and that is what
 * makes it expressible at all. `UnitFormatter.formatFuelRate(lPerHr, system)`
 * branched on the binary system, which is collapsed from VOLUME (spec D8), so
 * it was accidentally right about which quantity decides and wrong about which
 * unit that quantity names: it read the INSTANCE-wide mutable gallon static
 * (`getGallonStandard()`), so a `gal_uk` account on a US-default instance saw
 * a GPH figure computed on US gallons beside a volume column already showing
 * imperial ones. Here both come from `units.volume`, so there is nothing left
 * to disagree.
 *
 * ★ THE SUFFIX GOES ON EACH REPRESENTATION, NEVER ON THE COMPOSED STRING.
 * `"3.20 L/hr (0.70 gal/hr)"` states two rates; `"3.20 L (0.70 gal)/hr"`
 * states neither. This is `unit_formatting.format_rate`'s rule and the reason
 * this is a function here rather than a `QuantityFormat` member: `format`
 * composes the counterpart itself and has nowhere to put a per-side suffix.
 *
 * ★ ZERO IS A REAL RATE HERE, where the binary formatter answered `'N/A'`.
 * Volume is a linear quantity, so no fuel burned over an interval is 0.00 L/hr
 * and saying so is truthful; `'N/A'` claimed the figure was unknown. (Fuel
 * ECONOMY is the opposite case and keeps its `'N/A'` at zero by construction:
 * MPG is reciprocal, so a canonical zero has no finite value to print.)
 *
 * @param units The client's resolved unit set.
 * @param lPerHr The canonical rate, litres per hour.
 * @param showBoth Whether to append the counterpart representation.
 * @returns e.g. `'3.20 L/hr'`, `'0.85 gal/hr'`, or `'N/A'`.
 */
export function formatFuelRate(
  units: UnitSet,
  lPerHr: number | null | undefined,
  showBoth = false
): string {
  const adapter = adapterFor(units, 'volume')
  // Null short-circuits BEFORE the counterpart, exactly as `format` does.
  if (adapter.toDisplay(lPerHr) === null) return NOT_AVAILABLE
  const primary = `${render(adapter, lPerHr)}${PER_HOUR}`
  const counterpart = counterpartFor(units, 'volume')
  if (!showBoth || counterpart === null) return primary
  return `${primary} (${render(counterpart, lPerHr)}${PER_HOUR})`
}

/**
 * The compound label an engine-hours fuel rate is read under.
 *
 * Composed from the volume adapter rather than selected from two fixed
 * strings, for the reason `resolvedUnitSummary` gives at length.
 * `getFuelRateUnit(system)` could answer only `'L/hr'` or `'GPH'`, and `'GPH'`
 * names a gallon without saying which: the same three characters were shown to
 * a US-gallon and a UK-gallon account for two different numbers. `'gal/hr'`
 * matches the label the volume adapter puts on every other gallon in the app,
 * and matches what `unit_derived.format_fuel_rate` renders in a PDF.
 *
 * @param units The client's resolved unit set.
 * @returns e.g. `'L/hr'` or `'gal/hr'`.
 */
export function fuelRateLabel(units: UnitSet): string {
  return `${adapterFor(units, 'volume').label}${PER_HOUR}`
}

/**
 * How many of the reader's distance units a COST rate is quoted over.
 *
 * ★ NOT A CONVERSION FACTOR, and not a new decision either. These two numbers
 * are exactly what `UnitFormatter.formatCostPerDistance` has always used, and
 * what its label named in prose: a kilometre reader has always read cost per
 * 100 km and a mile reader cost per 1,000 mi. What moved is only WHICH of the
 * two a given account gets. The retired pair chose on the binary `UnitSystem`,
 * which spec D8 collapses from VOLUME, so a `{volume:'L', distance:'mi'}`
 * account read "Cost/100 km" beside an odometer column reading miles. Plan 3b
 * task 6 migrated that odometer and left this, so the two DISAGREED ON SCREEN
 * until now: before task 6 both were wrong together, which is less visible and
 * no more correct.
 *
 * A `Record` over the token rather than a ternary, for the reason
 * `PropaneRecordForm`'s example table gives: a distance unit added later cannot
 * compile without stating what it is quoted over, where an `else` arm would
 * silently answer 1,000 for it.
 *
 * The two conventions are not arbitrary and are not interchangeable: 100 km and
 * 1,000 mi are the denominators fuel-cost figures are published under in each
 * vocabulary, and they differ by more than the unit conversion does.
 */
const COST_PER_DISTANCE_OVER: Readonly<Record<UnitSet['distance'], number>> = {
  km: 100,
  mi: 1000,
}

/** Decimal places a currency figure is read at on a summary card. */
const COST_PER_DISTANCE_PRECISION = 2

/**
 * Render a cost-per-distance rate in the reader's OWN distance unit.
 *
 * ★ IT TAKES THE DISTANCE FROM THE RESOLVED SET, and it had to move files to do
 * it, exactly as `formatVolumePerDistance` did in task 6. `utils/units.ts`
 * cannot import `adapterFor`: `unitAdapters.ts` builds its table from
 * `UnitConverter` at module scope, so a runtime import back would form a cycle.
 * Left there, this would have needed a `KM_PER_DISTANCE_UNIT` map beside
 * `LITERS_PER_VOLUME_UNIT`, a second dispatch of a decision the adapter table
 * already makes, and a second copy of a unit decision is the defect this
 * workstream keeps unpicking. `formatCostPerVolume` stays in `units.ts` for the
 * mirror reason: it needs no adapter, only the litres-per-unit factor.
 *
 * The currency formatting is `formatCostPerVolume`'s, character for character,
 * rather than `formatUtils.formatCurrency`: that helper renders a zero as `'-'`
 * unless asked otherwise, and a zero cost per distance is a real figure a
 * vehicle with no fuel records legitimately reports.
 *
 * @param units The client's resolved unit set.
 * @param costPerKm The canonical rate, currency per kilometre.
 * @param currencyCode The reader's currency.
 * @param locale The reader's locale.
 * @returns e.g. `'$10.00'` per 100 km, or `'$160.93'` per 1,000 mi.
 */
export function formatCostPerDistance(
  units: UnitSet,
  costPerKm: number,
  currencyCode = 'USD',
  locale = 'en-US'
): string {
  // Cost per km to cost per one of the reader's distance units, then to cost
  // per however many of them the convention quotes. The canonical length of one
  // display unit is exactly what the distance adapter's `toCanonical(1)`
  // answers, so no mile factor is spelled here; the old code spelled `1.60934`
  // inline, a fourteenth copy of a constant `UnitConverter` already declared.
  // The non-null assertion rather than a `?? 1` fallback, for the reason
  // `formatVolumePerDistance` states: `1` is neither absent nor NaN, so the
  // fallback was unreachable, and a reachable one would quietly quote a mile
  // rate as a kilometre rate.
  const canonicalPerDistanceUnit = adapterFor(units, 'distance').toCanonical(1)!
  const over = COST_PER_DISTANCE_OVER[units.distance]
  return new Intl.NumberFormat(locale, {
    style: 'currency',
    currency: currencyCode,
    minimumFractionDigits: COST_PER_DISTANCE_PRECISION,
    maximumFractionDigits: COST_PER_DISTANCE_PRECISION,
  }).format(costPerKm * canonicalPerDistanceUnit * over)
}

/**
 * The denominator a cost-per-distance figure is read under, as a unit phrase.
 *
 * Composed from the distance adapter rather than selected from two fixed
 * strings, for the reason `resolvedUnitSummary` gives at length.
 * `getCostPerDistanceLabel` was such a selection AND it returned hardcoded
 * English: `'Cost/1k Miles'` and `'Cost/100 km'` bypassed i18n entirely, so
 * every reader of every language got those two strings. This returns only the
 * unit half; the "Cost/" is a translated key at the call site, which is the
 * same split `fuelList.avgFuelRate` uses.
 *
 * The number is grouped for the active locale, matching
 * `volumePerDistanceLabel`, so a French reader reads `1 000 mi`.
 *
 * @param units The client's resolved unit set.
 * @returns e.g. `'100 km'` or `'1,000 mi'`.
 */
export function costPerDistanceUnitLabel(units: UnitSet): string {
  const over = formatAtPrecision(COST_PER_DISTANCE_OVER[units.distance], 0)
  return `${over} ${adapterFor(units, 'distance').label}`
}

/**
 * Populate a unit-bearing form field, remembering where its value came from.
 *
 * @param canonical The stored canonical value, or null for an empty field.
 * @param quantity The formatter for the field's quantity.
 * @returns The field's display string and its canonical origin.
 */
export function seedUnitField(
  canonical: number | null | undefined,
  quantity: QuantityFormat
): UnitFieldOrigin {
  return { canonical: canonical ?? null, display: quantity.toInputValue(canonical) }
}

/**
 * Read a unit-bearing form field back into canonical storage.
 *
 * An untouched field returns the canonical value it was seeded from, NOT a
 * re-conversion of its display string: converting `7.50 mm` to `9/32 in` and
 * back yields `7.14375 mm`, so re-converting would corrupt a field the user
 * never edited. See the module docstring.
 *
 * ★ "Untouched" is a question about the QUANTITY, not about the characters,
 * and that distinction is a data defect rather than a nicety. `seedUnitField`
 * writes `toFixed(precision)`, so 9.07 kg seeds a pound field as `'20.00'`; a
 * `<select>` option value and a react-hook-form NUMBER field both round-trip
 * through `Number`, so the only string either can offer back is `'20'`. On
 * characters alone that reads as an edit and reconverts, storing 9.07184 kg in
 * a record the user only opened. Phase 3a task 3c met this on the fuel
 * odometer and sidestepped it by pinning `mi` and `km` to zero decimals, where
 * the two spellings coincide; mass carries two, so the sidestep does not reach
 * it. Comparing numerically covers both and needs no per-unit precision to
 * hold.
 *
 * The empty-origin guard is load bearing: `Number('')` is 0, so without it a
 * field that started empty would read a typed `0` as unchanged and store null.
 *
 * @param typed What the input currently holds.
 * @param origin What `seedUnitField` recorded for this field.
 * @param quantity The formatter for the field's quantity.
 * @returns The canonical value to store, or null when the field is empty or
 *   holds something that is not a number.
 */
export function canonicalFromUnitField(
  typed: string,
  origin: UnitFieldOrigin,
  quantity: QuantityFormat
): number | null {
  if (unitFieldUnchanged(typed, origin)) return origin.canonical
  if (typed.trim() === '') return null
  return quantity.toCanonical(Number(typed))
}

/**
 * Whether a seeded field still holds the QUANTITY it was populated with.
 *
 * ★ EXPORTED SO THERE IS ONE ANSWER TO "DID THE USER TOUCH THIS", and that is
 * the whole reason it is a function rather than three lines inlined twice.
 * Price is not a quantity (`decimalSafe.ts` explains at length why it cannot
 * borrow a `QuantityFormat`: a price adapter MULTIPLIES by the denominator
 * factor where a volume one divides), so it carries its own seed/read pair.
 * The untouched decision, though, is identical for both and it has already
 * been subtly wrong twice: once by comparing characters rather than the
 * number, and once by reading a typed `0` in a field that started empty as
 * unchanged. A second copy is a second place for the third mistake.
 *
 * The three legs, in order, because the order is load bearing:
 *
 *   1. the exact string, which is the common case and needs no arithmetic;
 *   2. a BLANK entry is a change, always. It has to be tested before the
 *      numeric leg, because `Number('')` is 0 and a field seeded with `'0.00'`
 *      would otherwise read a cleared box as untouched and keep the zero;
 *   3. the same number spelled differently. `seedUnitField` writes
 *      `toFixed(precision)`, so 9.07 kg seeds a pound field as `'20.00'` while
 *      a `<select>` and a react-hook-form NUMBER field can only hand back
 *      `'20'`. On characters alone that reads as an edit and reconverts,
 *      storing 9.07184 kg in a record the user only opened.
 *
 * The `origin.display !== ''` guard on leg 3 is what keeps a field that
 * STARTED empty from reading a typed `0` as unchanged and storing null.
 *
 * @param typed What the input currently holds.
 * @param origin What the field was seeded with.
 * @returns True when the stored value must be handed back unconverted.
 */
export function unitFieldUnchanged(typed: string, origin: UnitFieldOrigin): boolean {
  if (typed === origin.display) return true
  if (typed.trim() === '') return false
  return origin.display !== '' && Number(typed) === Number(origin.display)
}
