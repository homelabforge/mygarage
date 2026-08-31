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
 * ★ What this module deliberately does NOT do, and why (spec L6).
 * `backend/app/services/session_service.py::_get_current_odometer` reads
 * `param_key IN ("ODOMETER", "odometer", "ODO", "DISTANCE")`. Every one of those
 * is non-hex-prefixed, i.e. a CUSTOM PID that may already be in the user's own
 * unit, and none of them is the standard `A6-Odometer` that SAE J1979
 * guarantees is kilometres. Nothing in such a reading says which unit it holds,
 * and the backend discards the provenance at write time, so **no frontend rule
 * can recover it**. The only honest rendering is the raw number marked as
 * unverified, which is what `'unverified'` produces. That is a display fix, not
 * a fix for the underlying defect: the backend contract still has to record
 * which PID produced a value and whether it was normalised.
 *
 * Consumers of that column the deferred backend fix must cover, because a
 * frontend marker reaches none of them: `routes/fuel.py:194-213`, which turns
 * it into a PERSISTED `obc_l_per_100km` when a user accepts an OBC suggestion
 * (and persists `obc_avg_speed_kmh` from `session.avg_speed` in the same
 * write), and `routes/livelink_vehicle.py:708,732,748`, which exports it as a
 * labelled CSV column that leaves the product entirely.
 *
 * Native OBD2 units, all of which are the canonical metric ones the adapters
 * take: speed km/h, temperature °C, distance km, pressure kPa or bar. RPM,
 * percentage, voltage and time are outside the unit system entirely.
 */

import type { UnitQuantity } from '@/types/units'
import { UNIT_ADAPTERS } from './unitAdapters'
import { formatAtPrecision, type UnitFormat } from './unitFormat'

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
 * system and carries only a precision. `unverified` is the L6 case above: the
 * key says the value is a distance, and nothing says in which unit.
 */
export type TelemetryClass =
  | { readonly kind: 'quantity'; readonly quantity: UnitQuantity }
  | { readonly kind: 'dimensionless'; readonly precision: number }

/**
 * Decide what a telemetry parameter measures, from its key and reported unit.
 *
 * The only classifier in the codebase; see the module docstring.
 *
 * ★ Why a custom `SPEED` PID IS trusted while a custom `ODOMETER` is not, since
 * the asymmetry is deliberate and this is the one place it can be read.
 * `SPEED_PARAM_KEYS` on the backend is `["SPEED", "0D-VehicleSpeed",
 * "0D-VEHICLESPEED"]`, so a non-hex custom speed carries exactly the same
 * hazard. It is trusted anyway because the standard PID is the common case for
 * speed, where for the odometer the backend query reads ONLY custom keys, so
 * marking every speed unverified would cost a large regression to buy a rare
 * correctness win. The right fix for both halves is on the write side, and it
 * is the same fix: record which PID produced the value.
 *
 * @param paramKey The parameter key, e.g. `'A6-Odometer'` or `'COOLANT_TMP'`.
 * @param unit The unit string the device reported, if any.
 * @returns How the reading must be read.
 */
/** A two-hex-digit OBD2 PID prefix, e.g. the `A6-` of `A6-ODOMETER`. */
const OBD2_PID_PREFIX = /^[0-9A-Fa-f]{2}-/

/**
 * Bare distance keys the backend converts to kilometres on ingest.
 *
 * Mirrors `_ODOMETER_BARE_KEYS` in `backend/app/utils/odometer_units.py`,
 * lowercased. A bare key outside this set reaches the browser in whatever unit
 * the device reported, so it cannot be labelled.
 */
const NORMALISED_DISTANCE_KEYS = new Set([
  'odometer',
  'odo',
  'mileage',
  'total_distance',
  'distance_total',
])

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

  // Canonical kilometres, but only for the keys that actually are. A key is
  // canonical when it carries a two-hex-digit OBD2 prefix (a standard SAE
  // J1979 PID, which reports kilometres by specification) or when the backend
  // normalises it on ingest. That second set is `_ODOMETER_BARE_KEYS` in
  // `backend/app/utils/odometer_units.py` and must be kept level with it.
  //
  // Matching every key containing "distance" claimed more than that: a custom
  // autopid named `DISTANCE` is not in the backend's set, so it is stored in
  // whatever unit the device sent, and calling it kilometres made imperial
  // formatting divide a mileage figure by 1.609. Such a key falls through to a
  // plain number instead, which states nothing rather than something wrong.
  if (OBD2_PID_PREFIX.test(paramKey) || NORMALISED_DISTANCE_KEYS.has(key)) {
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
 * @param t The caller's translator, for the unknown-unit marker.
 * @returns The rendered number, its label, and whether that label is a claim.
 */
export function convertTelemetryValue(
  value: number,
  paramKey: string,
  unit: string | null,
  format: UnitFormat
): ConvertedTelemetry {
  const classified = classifyTelemetryParam(paramKey, unit)

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
