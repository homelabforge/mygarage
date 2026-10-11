import { describe, it, expect } from 'vitest'
import { isManufacturerCode } from '../dtc'

describe('isManufacturerCode', () => {
  it.each(['P1131', 'p1131', 'P3000', 'P33FF', 'B1342', 'B2000', 'C1000', 'C2000', 'U1900', 'U2000'])(
    '%s is in a maker-defined range',
    (code) => {
      expect(isManufacturerCode(code)).toBe(true)
    },
  )

  it.each(['P0420', 'P2000', 'P3400', 'P39FF', 'B0001', 'B3000', 'C0035', 'U0100', 'U3000', '', 'P113'])(
    '%j is not',
    (code) => {
      expect(isManufacturerCode(code)).toBe(false)
    },
  )
})
