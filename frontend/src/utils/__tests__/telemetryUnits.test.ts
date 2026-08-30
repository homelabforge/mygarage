/**
 * LiveLink's telemetry unit layer, after it was folded onto the shared adapter.
 *
 * Every expectation is a hand-written literal derived from the factor and the
 * input, never read off a run. The active Intl locale is `en-US` in tests
 * (`constants/i18n.ts` seeds it and nothing here changes it), so grouped output
 * uses a comma.
 *
 * ★ The unverified cases are the point of this file. `session_service.py`'s
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
  formatUnverifiedValue,
  getParamDisplayName,
} from '../telemetryUnits'
import { makeUnitFormat } from '../unitFormat'
import { presetUnitsFor } from '@/types/units'
import vehiclesEn from '@/locales/en/vehicles.json'

const IMPERIAL = makeUnitFormat(presetUnitsFor('imperial', 'us'))
const METRIC = makeUnitFormat(presetUnitsFor('metric', 'us'))

/** The marker the tabs render, resolved from the shipped English bundle. */
const UNKNOWN = vehiclesEn.livelink.unknownUnit

/** Stand-in for the component's `t`, resolving only the key under test. */
const t = ((key: string) =>
  key === 'vehicles:livelink.unknownUnit' ? UNKNOWN : key) as unknown as Parameters<
  typeof formatUnverifiedValue
>[1]

describe('the user-visible unknown-unit wording', () => {
  it('is exactly the string the English bundle ships', () => {
    expect(UNKNOWN).toBe('(unknown unit)')
  })
})

describe('classifyTelemetryParam', () => {
  it('routes a hex-prefixed odometer to distance, because SAE J1979 guarantees km', () => {
    expect(classifyTelemetryParam('A6-Odometer', null)).toStrictEqual({
      kind: 'quantity',
      quantity: 'distance',
    })
  })

  it('refuses to claim a unit for every custom key the backend odometer query reads', () => {
    for (const key of ['ODOMETER', 'odometer', 'ODO', 'DISTANCE']) {
      expect(classifyTelemetryParam(key, null)).toStrictEqual({ kind: 'unverified' })
    }
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
    expect(convertTelemetryValue(100, '0D-VehicleSpeed', 'km/h', IMPERIAL, t)).toStrictEqual({
      text: '62',
      unit: 'mph',
      unverified: false,
    })
  })

  it('converts temperature through the adapter (90 x 9/5 + 32 = 194 at 1 dp)', () => {
    expect(convertTelemetryValue(90, 'COOLANT_TMP', 'C', IMPERIAL, t)).toStrictEqual({
      text: '194.0',
      unit: '°F',
      unverified: false,
    })
  })

  it('converts kPa through the adapter (240 / 6.89476 = 34.809... at 1 dp)', () => {
    expect(convertTelemetryValue(240, 'MANIFOLD_PRESSURE', 'kPa', IMPERIAL, t)).toStrictEqual({
      text: '34.8',
      unit: 'PSI',
      unverified: false,
    })
  })

  it('canonicalises a bar reading to kPa first, so no bar-to-PSI factor is needed', () => {
    // 2.4 bar = 240 kPa exactly, then 240 / 6.89476 = 34.809...
    expect(convertTelemetryValue(2.4, 'MANIFOLD_PRESSURE', 'bar', IMPERIAL, t)).toStrictEqual({
      text: '34.8',
      unit: 'PSI',
      unverified: false,
    })
  })

  it('renders a bar reading in the metric preset own kPa, not in bar', () => {
    expect(convertTelemetryValue(2.4, 'MANIFOLD_PRESSURE', 'bar', METRIC, t)).toStrictEqual({
      text: '240',
      unit: 'kPa',
      unverified: false,
    })
  })

  it('converts a device-stated kilometre reading whose key names nothing', () => {
    // 8 km / 1.60934 = 4.97..., at the mi adapter's 0 dp.
    expect(convertTelemetryValue(8, 'TRIP_A', 'km', IMPERIAL, t)).toStrictEqual({
      text: '5',
      unit: 'mi',
      unverified: false,
    })
  })

  it('converts a standard odometer (1000 / 1.60934 = 621.37... at 0 dp)', () => {
    expect(convertTelemetryValue(1000, 'A6-Odometer', null, IMPERIAL, t)).toStrictEqual({
      text: '621',
      unit: 'mi',
      unverified: false,
    })
  })

  it('marks a custom odometer unverified instead of asserting miles', () => {
    expect(convertTelemetryValue(1000, 'ODOMETER', null, IMPERIAL, t)).toStrictEqual({
      text: '1,000',
      unit: '(unknown unit)',
      unverified: true,
    })
  })

  it('marks a custom DISTANCE unverified, where it used to be converted to miles', () => {
    expect(convertTelemetryValue(50, 'DISTANCE', null, IMPERIAL, t)).toStrictEqual({
      text: '50',
      unit: '(unknown unit)',
      unverified: true,
    })
  })

  it('leaves a dimensionless reading alone but still groups it at its precision', () => {
    expect(convertTelemetryValue(3200, 'ENGINE_RPM', 'rpm', IMPERIAL, t)).toStrictEqual({
      text: '3,200',
      unit: 'rpm',
      unverified: false,
    })
    expect(convertTelemetryValue(12.6, 'BATTERY_VOLTAGE', 'V', IMPERIAL, t)).toStrictEqual({
      text: '12.60',
      unit: 'V',
      unverified: false,
    })
  })

  it('answers metric without an early return, and the numbers are unchanged', () => {
    expect(convertTelemetryValue(100, '0D-VehicleSpeed', 'km/h', METRIC, t)).toStrictEqual({
      text: '100',
      unit: 'km/h',
      unverified: false,
    })
    expect(convertTelemetryValue(90, 'COOLANT_TMP', 'C', METRIC, t)).toStrictEqual({
      text: '90.0',
      unit: '°C',
      unverified: false,
    })
  })
})

describe('formatUnverifiedValue', () => {
  it('marks the raw value rather than dropping the suffix', () => {
    expect(formatUnverifiedValue(1000, t)).toBe('1,000 (unknown unit)')
  })

  it('renders the absent marker for a missing value, NaN included', () => {
    expect(formatUnverifiedValue(null, t)).toBe('--')
    expect(formatUnverifiedValue(undefined, t)).toBe('--')
    // NaN is absent, not a value: `formatAtPrecision` would render the string
    // "NaN" and the marker would then claim an unknown unit for a non-number.
    // Same policy as `unitAdapters.normalise`, which treats NaN as absent too.
    expect(formatUnverifiedValue(Number.NaN, t)).toBe('--')
  })
})

describe('getParamDisplayName', () => {
  it('prefers the supplied display name and otherwise cleans the key', () => {
    expect(getParamDisplayName('A6-Odometer', 'Total Distance')).toBe('Total Distance')
    expect(getParamDisplayName('COOLANT_TMP', null)).toBe('Coolant Tmp')
  })
})
