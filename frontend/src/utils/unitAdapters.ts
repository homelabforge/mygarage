/**
 * Conversion layer: one adapter per unit-preference token.
 *
 * The frontend mirror of `backend/app/utils/unit_adapters.py` (the adapter
 * table) and `unit_counterparts.py` (the show-both pairing, which is also
 * conversion: it returns adapters, not strings). Composition into a
 * human-readable string lives one layer up, in `utils/unitFormat.ts`, exactly
 * as `unit_formatting.py` sits on top of these two on the backend.
 *
 * **Everything here returns `number | null`. Nothing here returns a string.**
 * That split is the point: a conversion that renders is a conversion nobody can
 * reuse for a chart, a form field or an export, and the four parallel
 * conversion systems this workstream has been unpicking all started as a
 * renderer that happened to do arithmetic.
 *
 * Metric-canonical storage: every stored value is metric (see `UnitConverter`'s
 * module docstring for the full table). This module converts at the boundary
 * only and never changes a stored value.
 *
 * Two adapter shapes cover the ten quantities, matching the backend:
 * - `linear` covers proportional relationships
 *   (`canonical = (typed - offset) * factor`) and, with a non-zero `offset`,
 *   affine ones. Fahrenheit is the only affine token; every other linear token
 *   uses `offset = 0`, including the metric tokens whose typed unit IS the
 *   canonical unit (factor 1).
 * - `inverse` covers reciprocal relationships (MPG, km/L), where
 *   `canonical = numerator / typed` in both directions: a reciprocal relation
 *   is its own inverse. Zero is undefined there, and a real value here.
 *
 * ★ Two deliberate divergences from the backend, both forced by JavaScript
 * rather than chosen:
 *
 * 1. **Results are normalised to 12 significant digits.** The backend converts
 *    in `Decimal` and is exact. `number` is IEEE 754, so `34.8 * 6.89476`
 *    evaluates to `239.93764799999997`, and posting that to the API stores a
 *    value one ulp away from its own conversion. Twelve digits is what
 *    `UnitConverter.toCanonicalMetricString` already uses for the same reason,
 *    and it is lossless for every factor in the table: `9 * (25.4 / 32)` is
 *    still exactly `7.14375`.
 * 2. **`NaN` is treated as absent.** Form fields reach these functions through
 *    `Number(value)`, where a non-numeric entry yields `NaN` rather than
 *    throwing. Returning `NaN` would put `null`-shaped garbage into a JSON body
 *    that the schema accepts as a number.
 *
 * Neither converts a rounded DISPLAY value: rounding to a unit's declared
 * precision is a formatting decision and belongs to `unitFormat.ts`.
 */

import type { UnitQuantity, UnitSet } from '@/types/units'
import { UnitConverter } from './units'

/** Every token any quantity of a `UnitSet` can hold. */
export type UnitToken = UnitSet[UnitQuantity]

/**
 * 1/32 inch in millimetres, for the tire-tread `in32` adapter.
 *
 * Exact: 25.4 mm per inch / 32. Neither `25.4` nor its reciprocal existed
 * anywhere in `frontend/src` before this module, which is precisely why tread
 * depth was the one quantity the UI never converted (defect L4).
 */
const IN32_TO_MM = 25.4 / 32

/** L/100km per (km/L), i.e. the definition of "litres per hundred kilometres". */
const KM_L_NUMERATOR = 100

/** 1 bar = 100 kPa exactly, by SI definition (not derived from PSI_TO_BAR). */
const BAR_TO_KPA = 100

/** Celsius per Fahrenheit degree; the offset is applied separately. */
const F_TO_C_FACTOR = 5 / 9

/** The Fahrenheit scale's offset, in Fahrenheit degrees. */
const F_OFFSET = 32

/** Significant digits kept on every result. See the module docstring. */
const SIGNIFICANT_DIGITS = 12

/** Metres per kilometre. Canonical distance is km; maps and geo APIs take metres. */
const M_PER_KM = 1000

/** One typed unit's round trip to and from its canonical representation. */
export interface UnitAdapter {
  /** The `UnitSet` token this adapter serves, e.g. `'in32'`. */
  readonly unit: UnitToken
  /** The unit's display label, e.g. `'/32 in'`. */
  readonly label: string
  /** Decimal places this unit is read and entered at. */
  readonly precision: number
  /** Convert a canonical value into this adapter's typed unit. */
  toDisplay(canonical: number | null | undefined): number | null
  /** Convert a value in this adapter's typed unit into canonical. */
  toCanonical(typed: number | null | undefined): number | null
}

/**
 * Normalise one side of a conversion, or reject a value that is not one.
 *
 * @param value The raw arithmetic result, or an absent input.
 * @returns The value at 12 significant digits, or null when there is none.
 */
function normalise(value: number | null | undefined): number | null {
  if (value === null || value === undefined || Number.isNaN(value)) return null
  return Number(value.toPrecision(SIGNIFICANT_DIGITS))
}

/**
 * Build a proportional or affine adapter: `canonical = (typed - offset) * factor`.
 *
 * @param unit The token this adapter serves.
 * @param label The unit's display label.
 * @param precision Decimal places this unit is read and entered at.
 * @param factor Canonical units per typed unit.
 * @param offset Typed-unit offset; non-zero only for Fahrenheit.
 * @returns The adapter.
 */
function linear(
  unit: UnitToken,
  label: string,
  precision: number,
  factor: number,
  offset = 0
): UnitAdapter {
  return {
    unit,
    label,
    precision,
    toCanonical(typed) {
      const value = normalise(typed)
      return value === null ? null : normalise((value - offset) * factor)
    },
    toDisplay(canonical) {
      const value = normalise(canonical)
      return value === null ? null : normalise(value / factor + offset)
    },
  }
}

/**
 * Build a reciprocal adapter: `canonical = numerator / typed`, both directions.
 *
 * Self-inverse, since a reciprocal relationship inverts itself. Zero is
 * undefined (division by zero) in both directions, unlike a linear adapter,
 * where zero is a real value.
 *
 * @param unit The token this adapter serves.
 * @param label The unit's display label.
 * @param precision Decimal places this unit is read and entered at.
 * @param numerator The constant both directions divide.
 * @returns The adapter.
 */
function inverse(
  unit: UnitToken,
  label: string,
  precision: number,
  numerator: number
): UnitAdapter {
  const reciprocal = (value: number | null | undefined): number | null => {
    const n = normalise(value)
    if (n === null || n === 0) return null
    return normalise(numerator / n)
  }
  return { unit, label, precision, toCanonical: reciprocal, toDisplay: reciprocal }
}

/**
 * Every token's adapter, keyed by token.
 *
 * Labels and precisions match `unit_adapters.py`'s ADAPTERS table character for
 * character, with one exception: `c` and `f` carry the degree sign the UI has
 * always rendered, where the backend's PDF labels are a bare `C` and `F`.
 * Dropping it here would turn a later call-site migration into a visible
 * regression. (This used to cite `UnitFormatter.getTemperatureUnit` as the
 * thing still rendering it. Phase 3b task 2 deleted that method along with the
 * six other binary formatters no production file called, so these two labels
 * are now the only place the degree sign is decided.)
 */
export const UNIT_ADAPTERS: Readonly<Record<UnitToken, UnitAdapter>> = {
  // Distance
  km: linear('km', 'km', 0, 1),
  mi: linear('mi', 'mi', 0, UnitConverter.MILES_TO_KM),
  // Speed (same factor as distance, distinct token)
  kmh: linear('kmh', 'km/h', 0, 1),
  mph: linear('mph', 'mph', 0, UnitConverter.MILES_TO_KM),
  // Length
  m: linear('m', 'm', 2, 1),
  ft: linear('ft', 'ft', 2, UnitConverter.FEET_TO_METERS),
  // Volume
  L: linear('L', 'L', 2, 1),
  gal_us: linear('gal_us', 'gal', 2, UnitConverter.US_GALLONS_TO_LITERS),
  gal_uk: linear('gal_uk', 'gal', 2, UnitConverter.UK_GALLONS_TO_LITERS),
  // Consumption
  l_100km: linear('l_100km', 'L/100km', 2, 1),
  km_l: inverse('km_l', 'km/L', 2, KM_L_NUMERATOR),
  mpg_us: inverse('mpg_us', 'MPG', 1, UnitConverter.US_MPG_TO_L100KM),
  mpg_uk: inverse('mpg_uk', 'MPG', 1, UnitConverter.UK_MPG_TO_L100KM),
  // Pressure
  kpa: linear('kpa', 'kPa', 0, 1),
  bar: linear('bar', 'bar', 2, BAR_TO_KPA),
  psi: linear('psi', 'PSI', 1, UnitConverter.PSI_TO_KPA),
  // Temperature
  c: linear('c', '°C', 1, 1),
  f: linear('f', '°F', 1, F_TO_C_FACTOR, F_OFFSET),
  // Mass
  kg: linear('kg', 'kg', 2, 1),
  lb: linear('lb', 'lb', 2, UnitConverter.LBS_TO_KG),
  // Torque
  nm: linear('nm', 'Nm', 1, 1),
  lbft: linear('lbft', 'lb-ft', 1, UnitConverter.LBFT_TO_NM),
  // Tread
  mm: linear('mm', 'mm', 2, 1),
  in32: linear('in32', '/32 in', 0, IN32_TO_MM),
}

/**
 * Resolve the adapter for one of a resolved set's quantities.
 *
 * `secondary_gallon` is not a `UnitQuantity`, so asking for an adapter for it
 * does not compile. Neither does asking for `hours`, which is dimensionless and
 * outside the unit system entirely.
 *
 * @param units The client's resolved unit set.
 * @param quantity Which quantity to convert.
 * @returns The adapter for the token that set names.
 */
export function adapterFor(units: UnitSet, quantity: UnitQuantity): UnitAdapter {
  return UNIT_ADAPTERS[units[quantity]]
}

/**
 * The primary tokens whose counterpart is fixed regardless of `secondary_gallon`.
 *
 * Covers all 24 tokens except `L`, `l_100km` and `km_l`, whose counterpart's
 * gallon flavour is not derivable from the token itself (D4b).
 *
 * **Not symmetric, and that asymmetry is the spec, not a bug.** `bar` and `kpa`
 * both counterpart to `psi`, but `psi` counterparts to `kpa`, never `bar`.
 * `l_100km` and `km_l` both counterpart to an MPG flavour, but `mpg_us` and
 * `mpg_uk` counterpart to `l_100km`, never to each other.
 */
const FIXED_COUNTERPARTS: Readonly<Partial<Record<UnitToken, UnitToken>>> = {
  km: 'mi',
  mi: 'km',
  kmh: 'mph',
  mph: 'kmh',
  m: 'ft',
  ft: 'm',
  gal_us: 'L',
  gal_uk: 'L',
  mpg_us: 'l_100km',
  mpg_uk: 'l_100km',
  kpa: 'psi',
  bar: 'psi',
  psi: 'kpa',
  c: 'f',
  f: 'c',
  kg: 'lb',
  lb: 'kg',
  nm: 'lbft',
  lbft: 'nm',
  mm: 'in32',
  in32: 'mm',
}

/** D4b: the gallon a litre primary pairs with, by flavour. */
const VOLUME_COUNTERPART: Readonly<Record<UnitSet['secondary_gallon'], UnitToken>> = {
  us: 'gal_us',
  uk: 'gal_uk',
}

/** D4b: the MPG a flavourless metric consumption primary pairs with. */
const CONSUMPTION_COUNTERPART: Readonly<Record<UnitSet['secondary_gallon'], UnitToken>> = {
  us: 'mpg_us',
  uk: 'mpg_uk',
}

/**
 * Resolve the show-both counterpart adapter for one of a set's quantities.
 *
 * Mirrors `unit_counterparts.py::counterpart_for`. The counterpart of a litre
 * primary depends on `units.secondary_gallon` (D4b), which is why this takes the
 * whole set rather than a bare token: the counterpart of `L` cannot be derived
 * from `L` alone.
 *
 * @param units The client's resolved unit set.
 * @param quantity Which quantity to pair.
 * @returns The counterpart adapter, or null when the token has none.
 */
export function counterpartFor(units: UnitSet, quantity: UnitQuantity): UnitAdapter | null {
  const token = units[quantity]
  let counterpart: UnitToken | undefined
  if (token === 'L') {
    counterpart = VOLUME_COUNTERPART[units.secondary_gallon]
  } else if (token === 'l_100km' || token === 'km_l') {
    counterpart = CONSUMPTION_COUNTERPART[units.secondary_gallon]
  } else {
    counterpart = FIXED_COUNTERPARTS[token]
  }
  return counterpart === undefined ? null : UNIT_ADAPTERS[counterpart]
}

/**
 * Convert a search radius typed in the client's own distance unit into metres.
 *
 * ★ The one place a distance-to-metres conversion happens. Three hardcoded
 * copies of `1609.34` used to do this: `POIFinder` and `ShopFinder` each
 * branched on the binary `system`, and `LeafletMap` applied it UNCONDITIONALLY,
 * so a metric user picking a 25 km radius searched 25 km and was drawn a
 * 40.2 km circle. The binary branches were wrong in their own way: `system` is
 * collapsed from VOLUME (spec D8), so a custom user with litres and miles got
 * kilometre radii against a mile preference.
 *
 * Whole metres, because both consumers are metre-resolution: the search API's
 * integer `radius_meters` and a map circle's radius in metres.
 *
 * @param units The client's resolved unit set.
 * @param radius The radius as the user typed or selected it.
 * @returns The radius in whole metres, or null when there is no radius.
 */
export function radiusToMeters(units: UnitSet, radius: number | null | undefined): number | null {
  const km = adapterFor(units, 'distance').toCanonical(radius)
  return km === null ? null : Math.round(km * M_PER_KM)
}

/**
 * Convert a distance in metres into the client's own distance unit.
 *
 * The read half of `radiusToMeters`: the POI and shop search APIs report each
 * result's `distance_meters`, and both finders used to divide by 1000 and then
 * branch on the binary `system` to decide whether to convert. Exact, unrounded;
 * the caller picks a precision, and both finders deliberately show one decimal
 * rather than the km/mi adapter's own zero, which would collapse every nearby
 * result to "0 mi".
 *
 * @param units The client's resolved unit set.
 * @param meters The distance in metres.
 * @returns The distance in the set's distance unit, or null when there is none.
 */
export function metersToDistance(
  units: UnitSet,
  meters: number | null | undefined
): number | null {
  if (meters === null || meters === undefined || Number.isNaN(meters)) return null
  return adapterFor(units, 'distance').toDisplay(meters / M_PER_KM)
}
