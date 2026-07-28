import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook } from '@testing-library/react'

const setAccent = vi.fn()
let user: { accent_color?: string } | null = null

vi.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({ user }) }))
vi.mock('../../contexts/AccentContext', () => ({ useAccent: () => ({ setAccent }) }))

import { useAccentSync } from '../useAccentSync'

beforeEach(() => {
  vi.clearAllMocks()
  user = null
})

describe('useAccentSync', () => {
  it('applies the user’s saved accent when it is a supported key', () => {
    user = { accent_color: 'violet' }
    renderHook(() => useAccentSync())
    expect(setAccent.mock.calls).toStrictEqual([['violet']])
  })

  it('ignores an accent outside the supported set', () => {
    user = { accent_color: 'chartreuse' }
    renderHook(() => useAccentSync())
    expect(setAccent).not.toHaveBeenCalled()
  })

  it('does nothing for an unauthenticated (null) user', () => {
    user = null
    renderHook(() => useAccentSync())
    expect(setAccent).not.toHaveBeenCalled()
  })

  it('re-applies only when the DB accent value changes', () => {
    user = { accent_color: 'blue' }
    const { rerender } = renderHook(() => useAccentSync())
    expect(setAccent.mock.calls).toStrictEqual([['blue']])
    // Same value → effect dep unchanged → no extra apply.
    rerender()
    expect(setAccent.mock.calls).toStrictEqual([['blue']])
    // New value → one more apply.
    user = { accent_color: 'red' }
    rerender()
    expect(setAccent.mock.calls).toStrictEqual([['blue'], ['red']])
  })
})
