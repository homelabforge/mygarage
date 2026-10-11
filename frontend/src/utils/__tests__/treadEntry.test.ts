import { describe, expect, it } from 'vitest'

import { IMPERIAL_UNITS, METRIC_UNITS } from '../../__tests__/factories'
import { normaliseTreadEntry, thirtySecondsFromDecimalInches } from '../treadEntry'
import { makeUnitFormat } from '../unitFormat'

const in32 = makeUnitFormat(IMPERIAL_UNITS).tread
const mm = makeUnitFormat(METRIC_UNITS).tread

describe('thirtySecondsFromDecimalInches', () => {
  it('reads a gauge decimal as inches, to the nearest 32nd', () => {
    // The report: 0.346 in is 11.07/32 in.
    expect(thirtySecondsFromDecimalInches('.346', in32)).toBe('11')
    expect(thirtySecondsFromDecimalInches('0.346', in32)).toBe('11')
    expect(thirtySecondsFromDecimalInches('0.5', in32)).toBe('16')
    expect(thirtySecondsFromDecimalInches('0.0625', in32)).toBe('2')
    // Rounds to nearest, not down: 0.36 in is 11.52/32 in.
    expect(thirtySecondsFromDecimalInches('0.36', in32)).toBe('12')
  })

  it('leaves zero, whole 32nds and anything at or above an inch alone', () => {
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
    expect(normaliseTreadEntry('0.346', mm)).toBe('0.346')
  })
})

describe('normaliseTreadEntry', () => {
  it('rewrites a decimal-inch entry and passes everything else through', () => {
    expect(normaliseTreadEntry('.346', in32)).toBe('11')
    expect(normaliseTreadEntry('9', in32)).toBe('9')
    expect(normaliseTreadEntry('', in32)).toBe('')
  })
})
