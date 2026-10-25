/**
 * The browser calls a key an odometer exactly when the backend records one.
 *
 * Ingest converts an odometer to km by a substring scan
 * (`ODOMETER_NAME_PATTERNS` in backend/app/utils/odometer_units.py), so an
 * autopid named `ODOMETER_KM` arrives in km. The browser used to mirror an
 * exact six-name set instead and showed that km value as a plain number
 * (ruling FW-A-r2). The frontend CI job checks out the whole repository, so
 * this reads the backend's list directly.
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { isConvertedOdometerKey, ODOMETER_NAME_PATTERNS } from '../telemetryUnits'

const BACKEND_ODOMETER_UNITS = resolve(__dirname, '../../../../backend/app/utils/odometer_units.py')

function backendPatterns(source: string): string[] {
  const match = source.match(/^ODOMETER_NAME_PATTERNS = \(([^)]*)\)/m)
  if (!match) throw new Error('ODOMETER_NAME_PATTERNS not found as a tuple in odometer_units.py')
  return [...match[1].matchAll(/"([^"]+)"/g)].map((m) => m[1])
}

describe('odometer keys agree across the backend and the frontend', () => {
  it('uses the same substring scan', () => {
    const source = readFileSync(BACKEND_ODOMETER_UNITS, 'utf8')
    expect([...ODOMETER_NAME_PATTERNS]).toStrictEqual(backendPatterns(source))
  })

  it('takes the keys the scan takes, in any case', () => {
    for (const key of ['ODOMETER', 'odometer_km', 'ODOMETER_MI', 'TOTAL_ODO', 'MILEAGE', 'A6-Odometer']) {
      expect(isConvertedOdometerKey(key)).toBe(true)
    }
  })

  it('still leaves the trip counters out', () => {
    // Regression guard: the reason an exact set ever existed.
    for (const key of ['21-DISTANCEMILON', '31-DISTANCESINCECODECLEAR', 'DISTANCE', 'TRIP_METER']) {
      expect(isConvertedOdometerKey(key)).toBe(false)
    }
  })
})
