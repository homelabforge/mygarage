/**
 * LiveLink's telemetry unit layer, after it was folded onto the shared adapter.
 *
 * Every expectation is a hand-written literal derived from the factor and the
 * input, never read off a run. The active Intl locale is `en-US` in tests
 * (`constants/i18n.ts` seeds it and nothing here changes it), so grouped output
 * uses a comma.
 *
 * ★ Unit resolution is the point of this file. `session_service.py`'s
 * `_get_current_odometer` reads `param_key IN ("ODOMETER", "odometer", "ODO",
 * "DISTANCE")`, every one of which is non-hex-prefixed, i.e. a CUSTOM PID that
 * may already be in the user's own unit. Nothing in the reading says which, so
 * the only honest rendering is the raw number marked as unverified. This does
 * NOT fix that defect: the provenance is destroyed on the backend at write time
 * and no frontend rule can recover it.
 */
import { describe, it, expect } from 'vitest'
import {
  classifyTelemetryParam,
  convertTelemetryValue,
  getParamDisplayName,
} from '../telemetryUnits'
import { makeUnitFormat } from '../unitFormat'
import { presetUnitsFor } from '@/types/units'

const IMPERIAL = makeUnitFormat(presetUnitsFor('imperial', 'us'))
const METRIC = makeUnitFormat(presetUnitsFor('metric', 'us'))

/** The marker the tabs render, resolved from the shipped English bundle. */

/** Stand-in for the component's `t`, resolving only the key under test. */

describe('classifyTelemetryParam', () => {
  it('routes a hex-prefixed odometer to distance, because SAE J1979 guarantees km', () => {
    expect(classifyTelemetryParam('A6-Odometer', null)).toStrictEqual({
      kind: 'quantity',
      quantity: 'distance',
    })
  })

  it('routes a custom odometer to distance, because ingest now normalises it', () => {
    // The unverified marker existed because nothing recorded which unit a
    // custom-PID odometer held. Devices now declare an `odometer_unit`
    // (migration 096) and TelemetryService converts on the way in.
    //
    // Only for the keys ingest actually converts, though: this list is
    // `_ODOMETER_BARE_KEYS` in backend/app/utils/odometer_units.py. A bare
    // `DISTANCE` is NOT in it and is asserted the other way below.
    for (const key of ['ODOMETER', 'odometer', 'ODO', 'MILEAGE', 'TOTAL_DISTANCE']) {
      expect(classifyTelemetryParam(key, null)).toStrictEqual({
        kind: 'quantity',
        quantity: 'distance',
      })
    }
  })

  it('lets a declared unit beat a key-substring guess', () => {
    // '0B-IntakeManiAbsPress' contains "intake", which the temperature branch
    // matched before the pressure branch was ever reached, so intake MANIFOLD
    // PRESSURE rendered as 95.0 degF on a live dashboard. The device states kPa;
    // a substring in the name must not outvote it.
    expect(classifyTelemetryParam('0B-IntakeManiAbsPress', 'kPa')).toStrictEqual({
      kind: 'quantity',
      quantity: 'pressure',
    })
  })

  it('still classifies an intake AIR TEMP that declares no unit as temperature', () => {
    // The key heuristic is still the fallback when nothing is declared.
    expect(classifyTelemetryParam('0F-IntakeAirTemperature', null)).toStrictEqual({
      kind: 'quantity',
      quantity: 'temperature',
    })
  })

  it('accepts a custom odometer that states its own unit', () => {
    expect(classifyTelemetryParam('ODOMETER', 'km')).toStrictEqual({
      kind: 'quantity',
      quantity: 'distance',
    })
  })

  it('trusts a key it cannot name when the DEVICE states kilometres', () => {
    // The disjunct the old `detectParamType` carried and nothing reached: a key
    // that is neither speed, temperature, odometer nor distance, whose device
    // reports `km` anyway. Deleting the branch leaves it dimensionless, so the
    // value would render unconverted with a raw `km` label for a mile client.
    expect(classifyTelemetryParam('TRIP_A', 'km')).toStrictEqual({
      kind: 'quantity',
      quantity: 'distance',
    })
    expect(classifyTelemetryParam('TRIP_A', 'kilometers')).toStrictEqual({
      kind: 'quantity',
      quantity: 'distance',
    })
  })

  it('classifies speed, temperature and pressure by key or by reported unit', () => {
    expect(classifyTelemetryParam('0D-VehicleSpeed', null)).toStrictEqual({
      kind: 'quantity',
      quantity: 'speed',
    })
    expect(classifyTelemetryParam('COOLANT_TMP', null)).toStrictEqual({
      kind: 'quantity',
      quantity: 'temperature',
    })
    expect(classifyTelemetryParam('X', 'bar')).toStrictEqual({
      kind: 'quantity',
      quantity: 'pressure',
    })
  })

  it('gives every parameter outside the unit system its own precision', () => {
    expect(classifyTelemetryParam('ENGINE_RPM', 'rpm')).toStrictEqual({
      kind: 'dimensionless',
      precision: 0,
    })
    expect(classifyTelemetryParam('BATTERY_VOLTAGE', 'V')).toStrictEqual({
      kind: 'dimensionless',
      precision: 2,
    })
    expect(classifyTelemetryParam('THROTTLE', '%')).toStrictEqual({
      kind: 'dimensionless',
      precision: 1,
    })
  })
})

describe('convertTelemetryValue', () => {
  it('converts speed through the adapter (100 / 1.60934 = 62.137... at 0 dp)', () => {
    expect(convertTelemetryValue(100, '0D-VehicleSpeed', 'km/h', IMPERIAL)).toStrictEqual({
      text: '62',
      unit: 'mph',
    })
  })

  it('converts temperature through the adapter (90 x 9/5 + 32 = 194 at 1 dp)', () => {
    expect(convertTelemetryValue(90, 'COOLANT_TMP', 'C', IMPERIAL)).toStrictEqual({
      text: '194.0',
      unit: '°F',
    })
  })

  it('converts kPa through the adapter (240 / 6.89476 = 34.809... at 1 dp)', () => {
    expect(convertTelemetryValue(240, 'MANIFOLD_PRESSURE', 'kPa', IMPERIAL)).toStrictEqual({
      text: '34.8',
      unit: 'PSI',
    })
  })

  it('canonicalises a bar reading to kPa first, so no bar-to-PSI factor is needed', () => {
    // 2.4 bar = 240 kPa exactly, then 240 / 6.89476 = 34.809...
    expect(convertTelemetryValue(2.4, 'MANIFOLD_PRESSURE', 'bar', IMPERIAL)).toStrictEqual({
      text: '34.8',
      unit: 'PSI',
    })
  })

  it('renders a bar reading in the metric preset own kPa, not in bar', () => {
    expect(convertTelemetryValue(2.4, 'MANIFOLD_PRESSURE', 'bar', METRIC)).toStrictEqual({
      text: '240',
      unit: 'kPa',
    })
  })

  it('converts a device-stated kilometre reading whose key names nothing', () => {
    // 8 km / 1.60934 = 4.97..., at the mi adapter's 0 dp.
    expect(convertTelemetryValue(8, 'TRIP_A', 'km', IMPERIAL)).toStrictEqual({
      text: '5',
      unit: 'mi',
    })
  })

  it('converts a standard odometer (1000 / 1.60934 = 621.37... at 0 dp)', () => {
    expect(convertTelemetryValue(1000, 'A6-Odometer', null, IMPERIAL)).toStrictEqual({
      text: '621',
      unit: 'mi',
    })
  })

  it('renders a custom odometer in the reader\'s unit, now that ingest normalises it', () => {
    // Was '1,000 (unknown unit)'. The marker is retired because the stored
    // value is canonical km whatever key it arrived under: 1000 km -> 621 mi.
    expect(convertTelemetryValue(1000, 'ODOMETER', null, IMPERIAL)).toStrictEqual({
      text: '621',
      unit: 'mi',
    })
  })

  it('does NOT convert a custom DISTANCE, which ingest leaves in the device\'s unit', () => {
    // `_is_odometer_param` on the backend matches A6-/ODOMETER/ODO/MILEAGE/
    // DISTANCE_TOTAL/TOTAL_DISTANCE, so a bare `DISTANCE` autopid is stored
    // exactly as the device sent it. Reading it as kilometres and formatting
    // it imperially divided a mileage figure by 1.609. It is shown as the
    // plain number the device reported instead.
    expect(convertTelemetryValue(50, 'DISTANCE', null, IMPERIAL)).toStrictEqual({
      text: '50.0',
      unit: '',
    })
  })

  it('leaves a dimensionless reading alone but still groups it at its precision', () => {
    expect(convertTelemetryValue(3200, 'ENGINE_RPM', 'rpm', IMPERIAL)).toStrictEqual({
      text: '3,200',
      unit: 'rpm',
    })
    expect(convertTelemetryValue(12.6, 'BATTERY_VOLTAGE', 'V', IMPERIAL)).toStrictEqual({
      text: '12.60',
      unit: 'V',
    })
  })

  it('answers metric without an early return, and the numbers are unchanged', () => {
    expect(convertTelemetryValue(100, '0D-VehicleSpeed', 'km/h', METRIC)).toStrictEqual({
      text: '100',
      unit: 'km/h',
    })
    expect(convertTelemetryValue(90, 'COOLANT_TMP', 'C', METRIC)).toStrictEqual({
      text: '90.0',
      unit: '°C',
    })
  })
})


describe('getParamDisplayName', () => {
  it('prefers the supplied display name and otherwise cleans the key', () => {
    expect(getParamDisplayName('A6-Odometer', 'Total Distance')).toBe('Total Distance')
    expect(getParamDisplayName('COOLANT_TMP', null)).toBe('Coolant Tmp')
  })
})

describe('classifyTelemetryParam distance keys', () => {
  // The backend converts only the keys in `_ODOMETER_BARE_KEYS`
  // (backend/app/utils/odometer_units.py) plus anything carrying a standard
  // OBD2 PID prefix, which is kilometres by SAE J1979. Claiming kilometres for
  // any key containing "distance" over-reached: a custom `DISTANCE` autopid is
  // stored exactly as the device sent it, so an imperial reader saw a mileage
  // figure divided by 1.609.
  it('treats a standard PID odometer as canonical distance', () => {
    expect(classifyTelemetryParam('A6-ODOMETER', null)).toEqual({
      kind: 'quantity',
      quantity: 'distance',
    })
  })

  it('treats a bare ODOMETER autopid as canonical distance (the backend normalises it)', () => {
    expect(classifyTelemetryParam('ODOMETER', null)).toEqual({
      kind: 'quantity',
      quantity: 'distance',
    })
  })

  it('treats a standard PID trip counter as canonical distance', () => {
    expect(classifyTelemetryParam('31-DISTANCESINCECODECLEAR', null)).toEqual({
      kind: 'quantity',
      quantity: 'distance',
    })
  })

  it('does NOT claim kilometres for a custom DISTANCE autopid the backend never converts', () => {
    const result = classifyTelemetryParam('DISTANCE', null)
    expect(result.kind).not.toBe('quantity')
  })

  it('still honours a declared unit on a custom distance key', () => {
    expect(classifyTelemetryParam('DISTANCE', 'km')).toEqual({
      kind: 'quantity',
      quantity: 'distance',
    })
  })
})
