import { describe, expect, it } from 'vitest'

import { IMPERIAL_UNITS, METRIC_UNITS } from '../../__tests__/factories'
import { canonicalFromTreadField, thirtySecondsFromDecimalInches } from '../treadEntry'
import { makeUnitFormat, seedUnitField } from '../unitFormat'

const in32 = makeUnitFormat(IMPERIAL_UNITS).tread
const mm = makeUnitFormat(METRIC_UNITS).tread

describe('thirtySecondsFromDecimalInches', () => {
  it('reads a gauge decimal as inches, to the nearest 32nd', () => {
    // The report: 0.346 in is 11.07/32 in.
    expect(thirtySecondsFromDecimalInches('.346', in32)).toBe('11')
    expect(thirtySecondsFromDecimalInches('0.346', in32)).toBe('11')
    expect(thirtySecondsFromDecimalInches('0.5', in32)).toBe('16')
    expect(thirtySecondsFromDecimalInches('0.0625', in32)).toBe('2')
    // Nearest, not down: 0.36 in is 11.52/32 in.
    expect(thirtySecondsFromDecimalInches('0.36', in32)).toBe('12')
  })

  it('leaves zero, whole 32nds and anything from an inch up alone', () => {
    for (const typed of ['0', '11', '1', '1.5', '12.5']) {
      expect(thirtySecondsFromDecimalInches(typed, in32)).toBeNull()
    }
  })

  it('leaves blanks, junk and negatives alone', () => {
    for (const typed of ['', '   ', 'abc', '-0.3']) {
      expect(thirtySecondsFromDecimalInches(typed, in32)).toBeNull()
    }
  })

  it('never touches a millimetre field, where a decimal is an ordinary value', () => {
    expect(thirtySecondsFromDecimalInches('0.346', mm)).toBeNull()
  })
})

describe('canonicalFromTreadField', () => {
  // 8.40 mm is 10.58/32 in, so it seeds the field as 11, the 32nd 0.346 in rounds to.
  const seeded = seedUnitField(8.4, in32)

  it('stores a gauge decimal as its 32nd, even where the field was seeded with that 32nd', () => {
    expect(seeded.display).toBe('11')
    expect(canonicalFromTreadField('0.346', seeded, in32)).toBe(8.73125)
  })

  it('hands an untouched field back exactly as stored', () => {
    expect(canonicalFromTreadField('11', seeded, in32)).toBe(8.4)
  })

  it('treats a cleared field as cleared', () => {
    expect(canonicalFromTreadField('', seeded, in32)).toBeNull()
  })
})
