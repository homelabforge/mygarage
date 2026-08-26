/**
 * A UK user materialised to unit_preference='custom' by migration 093 must not
 * fall through to the imperial default. Before this, `user.unit_preference as
 * UnitSystem` handed 'custom' straight to `system === 'metric'` comparisons,
 * which silently answered "no" for every one of them: imperial values rendered
 * under metric labels.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook } from '@testing-library/react'
import { makeUnitSet, type User } from '@/__tests__/factories'

const h = vi.hoisted(() => ({ user: null as Partial<User> | null }))

vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({ user: h.user, isAuthenticated: h.user !== null }),
}))

import { useUnitPreference } from '../useUnitPreference'

describe('useUnitPreference with a custom unit_preference', () => {
  beforeEach(() => {
    localStorage.clear()
    h.user = null
  })

  it('derives imperial from a custom user whose resolved volume is a UK gallon', () => {
    h.user = {
      unit_preference: 'custom',
      show_both_units: true,
      resolved_units: makeUnitSet({ volume: 'gal_uk', secondary_gallon: 'uk' }),
    }

    const { result } = renderHook(() => useUnitPreference())

    expect(result.current.system).toBe('imperial')
    // The rest of the returned shape still passes through untouched.
    expect(result.current.showBoth).toBe(true)
  })

  it('derives imperial from a custom user whose resolved volume is a US gallon', () => {
    h.user = {
      unit_preference: 'custom',
      resolved_units: makeUnitSet({ volume: 'gal_us' }),
    }

    const { result } = renderHook(() => useUnitPreference())

    expect(result.current.system).toBe('imperial')
  })

  it('derives metric from a custom user whose resolved volume is litres', () => {
    h.user = {
      unit_preference: 'custom',
      resolved_units: makeUnitSet({ volume: 'L' }),
    }

    const { result } = renderHook(() => useUnitPreference())

    expect(result.current.system).toBe('metric')
  })

  it('falls back to imperial for a custom user with no resolved units', () => {
    h.user = { unit_preference: 'custom' }

    const { result } = renderHook(() => useUnitPreference())

    expect(result.current.system).toBe('imperial')
  })

  it('leaves a preset metric user on metric without consulting resolved units', () => {
    h.user = { unit_preference: 'metric' }

    const { result } = renderHook(() => useUnitPreference())

    expect(result.current.system).toBe('metric')
  })

  it('leaves a preset imperial user on imperial', () => {
    h.user = { unit_preference: 'imperial', resolved_units: makeUnitSet({ volume: 'gal_us' }) }

    const { result } = renderHook(() => useUnitPreference())

    expect(result.current.system).toBe('imperial')
  })

  it('falls back to imperial when the account carries no unit_preference at all', () => {
    // A browser holding a cached bundle against an older backend, or any
    // response shape that predates the column, must still render something.
    h.user = { username: 'someone' }

    const { result } = renderHook(() => useUnitPreference())

    expect(result.current.system).toBe('imperial')
  })

  it('still reads localStorage when logged out', () => {
    localStorage.setItem('unit_preference', 'metric')

    const { result } = renderHook(() => useUnitPreference())

    expect(result.current.system).toBe('metric')
  })
})
