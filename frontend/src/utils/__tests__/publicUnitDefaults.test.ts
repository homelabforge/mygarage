/**
 * The instance default unit set arrives as a JSON STRING inside a settings row,
 * not as a nested object, so every client that wants it has to parse it.
 *
 * The raw values below are copied verbatim from what the backend actually
 * serves: `app/migrations/093_add_unit_preferences.py:196` and
 * `app/services/settings_init.py` both write
 * `json.dumps(unit_set.model_dump(), sort_keys=True)`, and `/api/settings/public`
 * hands that string back untouched. They are pasted here as literals rather
 * than rebuilt from the parser's own vocabulary, so a parser that drifts from
 * the wire format fails instead of agreeing with itself.
 */
import { describe, it, expect } from 'vitest'
import type { UnitSet } from '@/types/units'
import {
  DEFAULT_UNIT_PREFS_KEY,
  gallonStandardFor,
  parseUnitSet,
  readPublicUnitDefaults,
} from '../publicUnitDefaults'

/** A hand-written complete set with the two gallon-bearing fields pinned. */
function makeSet(volume: UnitSet['volume'], secondaryGallon: UnitSet['secondary_gallon']): UnitSet {
  return {
    consumption: 'l_100km',
    distance: 'km',
    length: 'm',
    mass: 'kg',
    pressure: 'kpa',
    secondary_gallon: secondaryGallon,
    speed: 'kmh',
    temperature: 'c',
    torque: 'nm',
    tread: 'mm',
    volume,
  }
}

/** METRIC_PRESET, exactly as `/api/settings/public` serves it. */
const METRIC_RAW =
  '{"consumption": "l_100km", "distance": "km", "length": "m", "mass": "kg", "pressure": "kpa", "secondary_gallon": "us", "speed": "kmh", "temperature": "c", "torque": "nm", "tread": "mm", "volume": "L"}'

/** IMPERIAL_PRESET, exactly as `/api/settings/public` serves it. */
const IMPERIAL_RAW =
  '{"consumption": "mpg_us", "distance": "mi", "length": "ft", "mass": "lb", "pressure": "psi", "secondary_gallon": "us", "speed": "mph", "temperature": "f", "torque": "lbft", "tread": "in32", "volume": "gal_us"}'

/** UK_IMPERIAL_PRESET (migration 093's UK_IMPERIAL_SET), as served. */
const UK_IMPERIAL_RAW =
  '{"consumption": "mpg_uk", "distance": "mi", "length": "ft", "mass": "lb", "pressure": "psi", "secondary_gallon": "uk", "speed": "mph", "temperature": "f", "torque": "lbft", "tread": "in32", "volume": "gal_uk"}'

describe('parseUnitSet', () => {
  it('parses the metric preset the backend actually serves', () => {
    expect(parseUnitSet(METRIC_RAW)).toEqual({
      consumption: 'l_100km',
      distance: 'km',
      length: 'm',
      mass: 'kg',
      pressure: 'kpa',
      secondary_gallon: 'us',
      speed: 'kmh',
      temperature: 'c',
      torque: 'nm',
      tread: 'mm',
      volume: 'L',
    })
  })

  it('parses the US imperial preset', () => {
    expect(parseUnitSet(IMPERIAL_RAW)).toEqual({
      consumption: 'mpg_us',
      distance: 'mi',
      length: 'ft',
      mass: 'lb',
      pressure: 'psi',
      secondary_gallon: 'us',
      speed: 'mph',
      temperature: 'f',
      torque: 'lbft',
      tread: 'in32',
      volume: 'gal_us',
    })
  })

  it('parses the UK imperial preset', () => {
    expect(parseUnitSet(UK_IMPERIAL_RAW)).toEqual({
      consumption: 'mpg_uk',
      distance: 'mi',
      length: 'ft',
      mass: 'lb',
      pressure: 'psi',
      secondary_gallon: 'uk',
      speed: 'mph',
      temperature: 'f',
      torque: 'lbft',
      tread: 'in32',
      volume: 'gal_uk',
    })
  })

  it('returns null for a missing, null or empty value', () => {
    expect(parseUnitSet(undefined)).toBeNull()
    expect(parseUnitSet(null)).toBeNull()
    expect(parseUnitSet('')).toBeNull()
  })

  it('returns null for text that is not JSON', () => {
    expect(parseUnitSet('{not json')).toBeNull()
  })

  it('returns null for JSON that is not an object', () => {
    expect(parseUnitSet('[1, 2, 3]')).toBeNull()
    expect(parseUnitSet('"imperial"')).toBeNull()
    expect(parseUnitSet('null')).toBeNull()
  })

  it('returns null for a partial set rather than patching the gaps', () => {
    // Filling the missing quantities from an imperial default would hand a
    // metric instance imperial pressure, which is worse than an honest miss.
    // Mirrors `parse_default_unit_prefs`, which degrades whole.
    expect(parseUnitSet('{"volume": "L", "distance": "km"}')).toBeNull()
  })

  it('returns null when one quantity is absent', () => {
    const missingTread =
      '{"consumption": "l_100km", "distance": "km", "length": "m", "mass": "kg", "pressure": "kpa", "secondary_gallon": "us", "speed": "kmh", "temperature": "c", "torque": "nm", "volume": "L"}'
    expect(parseUnitSet(missingTread)).toBeNull()
  })

  it('returns null for an out-of-vocabulary token', () => {
    const badVolume =
      '{"consumption": "l_100km", "distance": "km", "length": "m", "mass": "kg", "pressure": "kpa", "secondary_gallon": "us", "speed": "kmh", "temperature": "c", "torque": "nm", "tread": "mm", "volume": "barrels"}'
    expect(parseUnitSet(badVolume)).toBeNull()
  })

  it('returns null for an unknown extra key, mirroring the model extra=forbid rule', () => {
    const extraKey =
      '{"consumption": "l_100km", "distance": "km", "gravity": "g", "length": "m", "mass": "kg", "pressure": "kpa", "secondary_gallon": "us", "speed": "kmh", "temperature": "c", "torque": "nm", "tread": "mm", "volume": "L"}'
    expect(parseUnitSet(extraKey)).toBeNull()
  })

  it('returns null when a quantity carries a non-string value', () => {
    const numericVolume =
      '{"consumption": "l_100km", "distance": "km", "length": "m", "mass": "kg", "pressure": "kpa", "secondary_gallon": "us", "speed": "kmh", "temperature": "c", "torque": "nm", "tread": "mm", "volume": 3}'
    expect(parseUnitSet(numericVolume)).toBeNull()
  })
})

describe('readPublicUnitDefaults', () => {
  it('finds the row by key and parses it', () => {
    const settings = [
      { key: 'auth_mode', value: 'none' },
      { key: DEFAULT_UNIT_PREFS_KEY, value: METRIC_RAW },
      { key: 'imperial_gallon_standard', value: 'us' },
    ]

    expect(readPublicUnitDefaults(settings)?.volume).toBe('L')
  })

  it('returns null when the payload carries no such row', () => {
    expect(readPublicUnitDefaults([{ key: 'auth_mode', value: 'none' }])).toBeNull()
  })

  it('returns null for an absent or empty settings list', () => {
    expect(readPublicUnitDefaults([])).toBeNull()
    expect(readPublicUnitDefaults(undefined)).toBeNull()
  })

  it('returns null when the row is present but unparseable', () => {
    const settings = [{ key: DEFAULT_UNIT_PREFS_KEY, value: '{not json' }]
    expect(readPublicUnitDefaults(settings)).toBeNull()
  })
})

describe('gallonStandardFor', () => {
  // D4b, mirroring backend `unit_formatting._forced_gallon_token`: a gallon
  // primary states its own flavour and wins outright; only a litre primary,
  // which has no flavour of its own, defers to `secondary_gallon`. Each input
  // is a hand-written literal, not something parseUnitSet produced, so this
  // block cannot pass by agreeing with the parser.
  it('takes a UK gallon primary as UK even when secondary_gallon says us', () => {
    expect(gallonStandardFor(makeSet('gal_uk', 'us'))).toBe('uk')
  })

  it('takes a US gallon primary as US even when secondary_gallon says uk', () => {
    expect(gallonStandardFor(makeSet('gal_us', 'uk'))).toBe('us')
  })

  it('defers to secondary_gallon for a litre primary', () => {
    expect(gallonStandardFor(makeSet('L', 'uk'))).toBe('uk')
    expect(gallonStandardFor(makeSet('L', 'us'))).toBe('us')
  })
})
