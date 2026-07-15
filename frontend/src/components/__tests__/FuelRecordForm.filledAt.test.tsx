import { describe, it, expect } from 'vitest'
import { splitFilledAt, joinFilledAt } from '../FuelRecordForm'

describe('filled_at split/join (issue #109)', () => {
  it('splits an ISO-ish value into date + 24h time', () => {
    expect(splitFilledAt('2026-04-30T22:00')).toEqual({ date: '2026-04-30', time: '22:00' })
  })

  it('splits null/empty to empty parts', () => {
    expect(splitFilledAt(null)).toEqual({ date: '', time: '' })
    expect(splitFilledAt('')).toEqual({ date: '', time: '' })
  })

  it('joins date + time into the submit string', () => {
    expect(joinFilledAt('2026-04-30', '22:00')).toBe('2026-04-30T22:00')
  })

  it('joins to empty when either part is missing', () => {
    expect(joinFilledAt('2026-04-30', '')).toBe('')
    expect(joinFilledAt('', '22:00')).toBe('')
  })
})
