/**
 * The country precedence: the vehicle's registration country, then this
 * person's own country (account, or this browser without one), then the
 * instance default, else null.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook } from '@testing-library/react'

const h = vi.hoisted(() => ({
  isAuthenticated: true,
  user: { country: null as string | null },
  defaultCountry: null as string | null,
}))

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({
    isAuthenticated: h.isAuthenticated,
    user: h.isAuthenticated ? h.user : null,
    defaultCountry: h.defaultCountry,
  }),
}))

import { useResolvedCountry } from '../useResolvedCountry'

beforeEach(() => {
  localStorage.clear()
  h.isAuthenticated = true
  h.user = { country: null }
  h.defaultCountry = null
})

describe('useResolvedCountry', () => {
  it('is null when nothing is set anywhere', () => {
    expect(renderHook(() => useResolvedCountry()).result.current).toBeNull()
  })

  it('falls back to the instance default', () => {
    h.defaultCountry = 'DE'
    expect(renderHook(() => useResolvedCountry()).result.current).toBe('DE')
  })

  it("prefers the person's own country over the instance default", () => {
    h.defaultCountry = 'DE'
    h.user = { country: 'FR' }
    expect(renderHook(() => useResolvedCountry()).result.current).toBe('FR')
  })

  it("prefers the vehicle's registration country over both", () => {
    h.defaultCountry = 'DE'
    h.user = { country: 'FR' }
    const { result } = renderHook(() => useResolvedCountry({ registration_country: 'LU' }))
    expect(result.current).toBe('LU')
  })

  it('reads this browser when there is no account', () => {
    h.isAuthenticated = false
    localStorage.setItem('country', 'it')
    expect(renderHook(() => useResolvedCountry()).result.current).toBe('IT')
  })

  it('ignores a code the app does not know', () => {
    h.user = { country: 'XX' }
    h.defaultCountry = 'ES'
    expect(renderHook(() => useResolvedCountry({ registration_country: 'ZZ' })).result.current).toBe('ES')
  })
})
