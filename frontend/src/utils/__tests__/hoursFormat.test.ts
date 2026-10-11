import { describe, expect, it } from 'vitest'

import { formatHours, hoursFromField } from '../hoursFormat'

describe('formatHours', () => {
  it('shows one decimal, grouped, with a fixed hr', () => {
    expect(formatHours(1234.5)).toBe('1,234.5 hr')
    expect(formatHours('812.4')).toBe('812.4 hr')
    expect(formatHours(0)).toBe('0.0 hr')
  })
})

describe('hoursFromField', () => {
  it('reads blank as unknown and keeps a typed 0', () => {
    expect(hoursFromField('')).toBeNull()
    expect(hoursFromField('   ')).toBeNull()
    expect(hoursFromField('0')).toBe(0)
    expect(hoursFromField('120.5')).toBe(120.5)
  })
})
