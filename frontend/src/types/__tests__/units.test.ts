/**
 * Spec D8: a `custom` user still has to give every binary consumer a defined
 * answer, and the resolved volume unit is what supplies it.
 */
import { describe, it, expect } from 'vitest'
import {
  UNIT_QUANTITIES,
  binarySystemFor,
  presetUnitsFor,
  type VolumeUnit,
} from '../units'
import { gallonStandardFor } from '@/utils/publicUnitDefaults'

/**
 * The whole volume vocabulary, mapped. Typed as `Record<VolumeUnit, ...>` so a
 * twelfth quantity or a fourth volume unit arriving from the backend fails to
 * compile here. `binarySystemFor` treats everything that is not litres as
 * imperial, so a new metric unit would otherwise be silently mislabelled.
 */
const EXPECTED: Record<VolumeUnit, 'metric' | 'imperial'> = {
  L: 'metric',
  gal_us: 'imperial',
  gal_uk: 'imperial',
}

describe('binarySystemFor', () => {
  it('maps litres to metric', () => {
    expect(binarySystemFor('L')).toBe('metric')
  })

  it('maps both gallon flavours to imperial', () => {
    expect(binarySystemFor('gal_us')).toBe('imperial')
    expect(binarySystemFor('gal_uk')).toBe('imperial')
  })

  it('covers every unit in the volume vocabulary', () => {
    // The annotation forces this literal to be exhaustive: a new member of the
    // union is a compile error, not a quietly untested case.
    const actual: Record<VolumeUnit, 'metric' | 'imperial'> = {
      L: binarySystemFor('L'),
      gal_us: binarySystemFor('gal_us'),
      gal_uk: binarySystemFor('gal_uk'),
    }
    expect(actual).toStrictEqual(EXPECTED)
  })
})

/**
 * The presets, which have to answer for the two rungs of `useUnitPreference`
 * that hold a binary system and a gallon flavour rather than a resolved set:
 * an explicit anonymous choice, and the post-093 fallback.
 *
 * The expectations below are hand-written against `app/constants/units.py`'s
 * `METRIC_PRESET` / `IMPERIAL_PRESET` and `app/utils/default_unit_prefs.py`'s
 * `UK_IMPERIAL_PRESET`, never derived from the constants under test.
 */
describe('presetUnitsFor', () => {
  it('reproduces the backend imperial preset for a US gallon browser', () => {
    expect(presetUnitsFor('imperial', 'us')).toStrictEqual({
      distance: 'mi',
      speed: 'mph',
      length: 'ft',
      volume: 'gal_us',
      consumption: 'mpg_us',
      pressure: 'psi',
      temperature: 'f',
      mass: 'lb',
      torque: 'lbft',
      tread: 'in32',
      secondary_gallon: 'us',
    })
  })

  it('reproduces the backend metric preset for a US gallon browser', () => {
    expect(presetUnitsFor('metric', 'us')).toStrictEqual({
      distance: 'km',
      speed: 'kmh',
      length: 'm',
      volume: 'L',
      consumption: 'l_100km',
      pressure: 'kpa',
      temperature: 'c',
      mass: 'kg',
      torque: 'nm',
      tread: 'mm',
      secondary_gallon: 'us',
    })
  })

  it('applies the three UK-imperial overrides and nothing else', () => {
    // `default_unit_prefs.py` derives UK-imperial from the imperial preset by
    // replacing exactly volume, consumption and secondary_gallon.
    const us = presetUnitsFor('imperial', 'us')
    const uk = presetUnitsFor('imperial', 'uk')

    expect(us.volume).toBe('gal_us')
    expect(uk.volume).toBe('gal_uk')
    expect(uk.consumption).toBe('mpg_uk')
    expect(uk.secondary_gallon).toBe('uk')
    expect(uk.pressure).toBe('psi')
    expect(uk.distance).toBe('mi')
  })

  it('carries the gallon flavour on a metric set, where volume cannot state it', () => {
    // A litre primary has no flavour of its own, so `secondary_gallon` is the
    // only place a UK browser's choice can survive into the set.
    expect(presetUnitsFor('metric', 'us').secondary_gallon).toBe('us')
    expect(presetUnitsFor('metric', 'uk').secondary_gallon).toBe('uk')
    expect(presetUnitsFor('metric', 'uk').volume).toBe('L')
  })

  it('round-trips through the two collapses that read it back', () => {
    // `binarySystemFor` and `gallonStandardFor` are what `useUnitPreference`
    // uses to derive `system` and `gallonStandard`; a preset that did not
    // round-trip would make the hook disagree with itself.
    for (const system of ['imperial', 'metric'] as const) {
      for (const gallon of ['us', 'uk'] as const) {
        const set = presetUnitsFor(system, gallon)
        expect(binarySystemFor(set.volume)).toBe(system)
        expect(gallonStandardFor(set)).toBe(gallon)
      }
    }
  })

  it('hands back a stable identity so a memo on it does not thrash', () => {
    expect(presetUnitsFor('metric', 'uk')).toBe(presetUnitsFor('metric', 'uk'))
    expect(presetUnitsFor('metric', 'uk')).not.toBe(presetUnitsFor('metric', 'us'))
  })
})

describe('UNIT_QUANTITIES', () => {
  it('lists the ten convertible quantities and omits secondary_gallon', () => {
    expect([...UNIT_QUANTITIES]).toStrictEqual([
      'distance',
      'speed',
      'length',
      'volume',
      'consumption',
      'pressure',
      'temperature',
      'mass',
      'torque',
      'tread',
    ])
  })

  it('names every key of a resolved set except the flavour hint', () => {
    const set = presetUnitsFor('metric', 'us')
    expect(Object.keys(set).filter((k) => k !== 'secondary_gallon').sort()).toStrictEqual(
      [...UNIT_QUANTITIES].sort()
    )
  })
})
