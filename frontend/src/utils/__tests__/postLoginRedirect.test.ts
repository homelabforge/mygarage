import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { resolvePostLoginRoute } from '../postLoginRedirect'

// We mock the mobile module so tests are deterministic regardless of test environment UA
vi.mock('../mobile', () => ({
  isMobileBrowser: vi.fn(),
}))

import { isMobileBrowser } from '../mobile'

const mockIsMobile = isMobileBrowser as ReturnType<typeof vi.fn>

describe('resolvePostLoginRoute', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('returns /quick-entry when mobile and setting enabled', () => {
    mockIsMobile.mockReturnValue(true)
    const user = { mobile_quick_entry_enabled: true }
    expect(resolvePostLoginRoute(user)).toBe('/quick-entry')
  })

  it('returns / when desktop regardless of setting', () => {
    mockIsMobile.mockReturnValue(false)
    const user = { mobile_quick_entry_enabled: true }
    expect(resolvePostLoginRoute(user)).toBe('/')
  })

  it('returns / when mobile but setting disabled', () => {
    mockIsMobile.mockReturnValue(true)
    const user = { mobile_quick_entry_enabled: false }
    expect(resolvePostLoginRoute(user)).toBe('/')
  })

  it('returns / when mobile and setting is undefined (not set)', () => {
    mockIsMobile.mockReturnValue(true)
    const user = {}
    expect(resolvePostLoginRoute(user)).toBe('/')
  })

  it('returns / when desktop and setting disabled', () => {
    mockIsMobile.mockReturnValue(false)
    const user = { mobile_quick_entry_enabled: false }
    expect(resolvePostLoginRoute(user)).toBe('/')
  })
})
