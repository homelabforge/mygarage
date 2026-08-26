/**
 * Spec D8: a `custom` user still has to give every binary consumer a defined
 * answer, and the resolved volume unit is what supplies it.
 */
import { describe, it, expect } from 'vitest'
import { binarySystemFor, type VolumeUnit } from '../units'

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
