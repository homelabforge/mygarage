/**
 * `asTimeFormat` normalises an unvalidated preference instead of passing it
 * through.
 *
 * `users.time_format` is a plain VARCHAR with no database CHECK, so the
 * generated schema types it as `string`. The previous
 * `(user.time_format as TimeFormat) || '12h'` cast handed any non-empty value
 * straight to consumers that only ever compare against '24h', so a hand-edited
 * row rendered on a 12-hour clock by accident rather than by rule. This pins
 * the rule.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook } from '@testing-library/react'
import { asTimeFormat } from '../useTimeFormat'

const h = vi.hoisted(() => ({ user: null as { time_format?: string } | null }))

vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({ user: h.user, isAuthenticated: h.user !== null }),
}))

import { useTimeFormat } from '../useTimeFormat'

describe('asTimeFormat', () => {
  it('passes the two recognised values through', () => {
    expect(asTimeFormat('24h')).toBe('24h')
    expect(asTimeFormat('12h')).toBe('12h')
  })

  it('normalises every unrecognised string to 12h', () => {
    // Includes near misses, which are the ones a `as TimeFormat` cast would
    // have carried into consumers unchanged.
    for (const value of ['24H', 'H24', '24', 'military', 'twelve', ' 24h', '']) {
      expect(asTimeFormat(value)).toBe('12h')
    }
  })

  it('normalises absent values to 12h', () => {
    expect(asTimeFormat(null)).toBe('12h')
    expect(asTimeFormat(undefined)).toBe('12h')
  })
})

describe('useTimeFormat', () => {
  beforeEach(() => {
    localStorage.clear()
    h.user = null
  })

  it('normalises an authenticated user stored preference through asTimeFormat', () => {
    h.user = { time_format: 'military' }

    const { result } = renderHook(() => useTimeFormat())

    expect(result.current.timeFormat).toBe('12h')
  })

  it('reads a recognised authenticated preference', () => {
    h.user = { time_format: '24h' }

    const { result } = renderHook(() => useTimeFormat())

    expect(result.current.timeFormat).toBe('24h')
  })

  it('normalises the stored localStorage value when logged out', () => {
    localStorage.setItem('time_format', 'military')

    const { result } = renderHook(() => useTimeFormat())

    expect(result.current.timeFormat).toBe('12h')
  })

  it('reads a recognised localStorage value when logged out', () => {
    localStorage.setItem('time_format', '24h')

    const { result } = renderHook(() => useTimeFormat())

    expect(result.current.timeFormat).toBe('24h')
  })
})
