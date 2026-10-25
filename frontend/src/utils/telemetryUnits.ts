/**
 * LiveLink's unit layer: classify an OBD2 parameter, then render it through the
 * SAME adapter table every other screen uses.
 *
 * This module used to be a parallel conversion system. It carried four
 * hardcoded factors of its own (`KM_TO_MILES`, `KPA_TO_PSI`, a `barToPsi` of
 * `14.5038` nobody had ever listed, and the `9/5 + 32` Celsius idiom), two
 * independent key-sniffing heuristics that disagreed with each other, and its
 * own number formatting. Every one of those is now `utils/unitAdapters.ts` and
 * `utils/unitFormat.ts` doing the work, so a factor exists once and a
 * per-quantity `custom` user is served here as well as anywhere else.
 *
 * ★ ONE detection heuristic. `classifyTelemetryParam` is the only function in
 * the codebase that decides what an OBD2 parameter measures. It used to have a
 * sibling: `formatTelemetryValue` re-sniffed the same key against a DIFFERENT
 * substring list to pick decimal places, so a parameter could be a distance to
 * one and an unclassified value to the other. Precision now comes from the
 * adapter for anything the unit system covers, and from this same classifier
 * for anything outside it (RPM, voltage, percentages).
 *
 * ★ Odometers. The backend stores an odometer it normalises in kilometres
 * and labels its parameter row `km` (FB-5, and migration 133 for rows from
 * before), so a row that says km renders as a distance, whatever the key is
 * called. Which keys get normalised depends on the device's kind (a WiCAN's
 * name scan, any other kind's declared key), which this classifier can't see,
 * so it trusts the label rather than the name (FW-A-r3). A standard PID that
 * names a distance is km by SAE J1979 and renders as one too. Anything else
 * (a custom `TOTAL_ODO` a generic topic sent in miles, a `DISTANCE` autopid)
 * renders as a plain number with whatever unit came with it, which says
 * nothing rather than something wrong.
 *
 * Native OBD2 units, all of which are the canonical metric ones the adapters
 * take: speed km/h, temperature °C, distance km, pressure kPa or bar. RPM,
 * percentage, voltage and time are outside the unit system entirely.
 */

import type { UnitQuantity } from '@/types/units'
import { UNIT_ADAPTERS } from './unitAdapters'
import { formatAtPrecision, type UnitFormat } from './unitFormat'
import { UnitConverter } from './units'

/**
 * Unit symbols a device may declare, mapped to what they measure. Consulted
 * BEFORE any key-substring heuristic, because a declaration is evidence and a
 * substring is a guess.
 */
const UNIT_BY_DECLARED_SYMBOL: Readonly<Record<string, UnitQuantity>> = {
  'km/h': 'speed',
  kmh: 'speed',
  '°c': 'temperature',
  c: 'temperature',
  celsius: 'temperature',
  km: 'distance',
  kilometers: 'distance',
  kpa: 'pressure',
  bar: 'pressure',
}

/** A millimetre reading in inches, and as itself. A propane tank's depth
 *  moves a few millimetres per percent. */
const INCH_PRECISION = 1
const MILLIMETRE_PRECISION = 0

/** Decimals for a parameter outside the unit system, by kind. */
const RPM_PRECISION = 0
const VOLTAGE_PRECISION = 2
const DIMENSIONLESS_PRECISION = 1

/** One telemetry reading, ready to render. */
export interface ConvertedTelemetry {
  /** The value as the user reads it: grouped, at the resolved unit's precision. */
  readonly text: string
  /** The label for that value, or `''` when the parameter carries none. */
  readonly unit: string
}

/**
 * What a telemetry parameter measures.
 *
 * `quantity` is convertible: the reading is canonical metric and an adapter
 * owns both the factor and the precision. `dimensionless` is outside the unit
 * system and carries only a precision. `millimetres` is a declared mm (a
 * propane tank's depth), which the unit system has no quantity for.
 */
export type TelemetryClass =
  | { readonly kind: 'quantity'; readonly quantity: UnitQuantity }
  | { readonly kind: 'dimensionless'; readonly precision: number }
  | { readonly kind: 'millimetres' }

/**
 * Decide what a telemetry parameter measures, from its key and reported unit.
 *
 * The only classifier in the codebase; see the module docstring.
 *
 * ★ Why any key with "speed" in it reads as km/h. Upstream WiCAN defines a
 * bare `SPEED` as km/h, and a reading the device declares in mph is converted
 * to km/h on ingest, so what's stored is km/h either way. The one hole is a
 * custom mph autopid with no declared unit: it arrives raw and reads as km/h
 * here. That's a write-side gap, and no key rule in the browser can see it.
 *
 * @param paramKey The parameter key, e.g. `'A6-Odometer'` or `'COOLANT_TMP'`.
 * @param unit The unit string the device reported, if any.
 * @returns How the reading must be read.
 */
/** A two-hex-digit OBD2 PID prefix, e.g. the `A6-` of `A6-ODOMETER`. */
const OBD2_PID_PREFIX = /^[0-9A-Fa-f]{2}-/

export function classifyTelemetryParam(paramKey: string, unit: string | null): TelemetryClass {
  const key = paramKey.toLowerCase()
  const unitLower = (unit ?? '').toLowerCase()

  // ★ A DECLARED unit outranks every key-substring guess below. The device
  // states this in its config block, so it is evidence where the key is only a
  // hint, and the hints overlap: '0B-IntakeManiAbsPress' contains "intake" and
  // was matched by the temperature branch before the pressure branch was
  // reached, rendering intake manifold PRESSURE as 95.0 degF on a live
  // dashboard. Ordering the substring lists more carefully would only move the
  // collision somewhere else; deferring to the declaration removes the class.
  const declared = UNIT_BY_DECLARED_SYMBOL[unitLower]
  if (declared) return { kind: 'quantity', quantity: declared }
  // The unit system has no small-length quantity (`tread` is 32nds of an
  // inch, `length` is metres or feet), so a declared mm has a class of its own.
  if (unitLower === 'mm') return { kind: 'millimetres' }

  if (key.includes('speed')) {
    return { kind: 'quantity', quantity: 'speed' }
  }

  if (
    key.includes('temp') ||
    key.includes('coolant') ||
    key.includes('ambient') ||
    key.includes('intake')
  ) {
    return { kind: 'quantity', quantity: 'temperature' }
  }

  // Canonical kilometres, but only where that's known. A custom odometer is
  // km when its row says so, which the declared-unit lookup above already
  // took: the backend labels every odometer it normalises km. Whether it did
  // depends on the device's kind (a WiCAN scans names, anything else records
  // only its declared key), and the browser can't see that, so no name rule
  // here guesses it (FW-A-r3). The one key rule left is a two-hex-digit OBD2
  // prefix naming a distance: a standard SAE J1979 PID, km by specification.
  //
  // Anything else falls through to a plain number with whatever unit it
  // carries, which states nothing rather than something wrong: a generic
  // topic's `TOTAL_ODO` in miles used to read 0.62x as km.
  if (OBD2_PID_PREFIX.test(paramKey)) {
    if (key.includes('odo') || key.includes('distance') || key.includes('mileage')) {
      return { kind: 'quantity', quantity: 'distance' }
    }
  }

  if (key.includes('press') || key.includes('baro') || key.includes('manifold')) {
    return { kind: 'quantity', quantity: 'pressure' }
  }

  if (key.includes('rpm')) return { kind: 'dimensionless', precision: RPM_PRECISION }
  if (key.includes('volt') || key.includes('battery')) {
    return { kind: 'dimensionless', precision: VOLTAGE_PRECISION }
  }
  return { kind: 'dimensionless', precision: DIMENSIONLESS_PRECISION }
}

/**
 * Convert and format one telemetry reading for the client's resolved units.
 *
 * @param value The raw value the device reported.
 * @param paramKey The parameter key.
 * @param unit The unit string the device reported, if any.
 * @param format The client's resolved formatters, from `useUnitFormat()`.
 * @returns The rendered number and its label.
 */
export function convertTelemetryValue(
  value: number,
  paramKey: string,
  unit: string | null,
  format: UnitFormat
): ConvertedTelemetry {
  const classified = classifyTelemetryParam(paramKey, unit)

  if (classified.kind === 'millimetres') {
    // Follows the account's LENGTH choice: feet reads inches, metres reads
    // millimetres. The inch is UnitConverter's, so no factor is new here.
    if (format.length.unit === 'ft') {
      return {
        text: formatAtPrecision(value / 1000 / UnitConverter.INCH_TO_METERS, INCH_PRECISION),
        unit: 'in',
      }
    }
    return { text: formatAtPrecision(value, MILLIMETRE_PRECISION), unit: 'mm' }
  }

  if (classified.kind === 'dimensionless') {
    return {
      text: formatAtPrecision(value, classified.precision),
      unit: unit ?? '',
    }
  }

  const quantity = format[classified.quantity]
  // Canonical pressure is kPa; a bar reading is canonicalised through the
  // adapter table rather than through a bar-to-PSI factor of its own, which is
  // how `barToPsi = 14.5038` came to exist here in the first place.
  const canonical =
    classified.quantity === 'pressure' && (unit ?? '').toLowerCase() === 'bar'
      ? UNIT_ADAPTERS.bar.toCanonical(value)
      : value
  return { text: quantity.toDisplayText(canonical), unit: quantity.label }
}


/**
 * Get display name for a parameter with unit-aware formatting.
 *
 * A NAMING heuristic, not a unit one: it never decides what a parameter
 * measures, so it is not a second classifier.
 *
 * @param paramKey The parameter key.
 * @param displayName The name the device supplied, if any.
 * @returns The name to render.
 */
export function getParamDisplayName(paramKey: string, displayName: string | null): string {
  if (displayName) return displayName

  // Clean up common OBD2 parameter keys
  const key = paramKey
    .replace(/^[0-9A-F]{2}-/i, '') // Remove hex prefix like "0D-"
    .replace(/([a-z])([A-Z])/g, '$1 $2') // Add spaces between camelCase
    .replace(/_/g, ' ') // Replace underscores with spaces

  // Capitalize first letter of each word
  return key
    .split(' ')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(' ')
}
