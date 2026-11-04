/**
 * useDateFormatSync is the only thing between the saved preference and the
 * non-React date formatters, so drop it and every date stays month-first while
 * the control says day-first.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { act, renderHook } from '@testing-library/react'

const h = vi.hoisted(() => ({
  isAuthenticated: true,
  user: null as Record<string, string> | null,
  emit: vi.fn(),
  changeLanguage: vi.fn(),
}))

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({ isAuthenticated: h.isAuthenticated, user: h.user }),
}))

vi.mock('react-i18next', () => {
  const i18n = { language: 'en', emit: h.emit, changeLanguage: h.changeLanguage }
  return { useTranslation: () => ({ t: (k: string) => k, i18n }) }
})

import { getActiveDateLocale, setActiveDateFormat, setActiveLocale } from '@/constants/i18n'
import { useDateFormatSync } from '../useDateFormatSync'

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  h.isAuthenticated = true
  h.user = { date_format: 'mdy' }
  setActiveLocale('en')
  setActiveDateFormat('mdy')
})

afterEach(() => {
  setActiveDateFormat('mdy')
})

describe('useDateFormatSync', () => {
  it("publishes the account's day-first choice and re-renders the page, language unchanged", () => {
    h.user = { date_format: 'dmy' }
    renderHook(() => useDateFormatSync())

    expect(getActiveDateLocale()).toBe('en-GB')
    expect(h.emit.mock.calls).toStrictEqual([['languageChanged', 'en']])
    expect(h.changeLanguage).not.toHaveBeenCalled()
  })

  it('stays quiet while the format is unchanged, and announces a change', () => {
    const { rerender } = renderHook(() => useDateFormatSync())
    // Already month-first: nothing to announce.
    expect(h.emit).not.toHaveBeenCalled()

    h.user = { date_format: 'dmy' }
    rerender()
    expect(getActiveDateLocale()).toBe('en-GB')
    expect(h.emit).toHaveBeenCalledTimes(1)

    rerender()
    expect(h.emit).toHaveBeenCalledTimes(1)

    h.user = { date_format: 'mdy' }
    rerender()
    expect(getActiveDateLocale()).toBe('en-US')
    expect(h.emit).toHaveBeenCalledTimes(2)
  })

  it("follows this browser's copy when there is no account", () => {
    h.isAuthenticated = false
    h.user = null
    renderHook(() => useDateFormatSync())
    expect(getActiveDateLocale()).toBe('en-US')

    act(() => {
      localStorage.setItem('date_format', 'dmy')
      window.dispatchEvent(
        new StorageEvent('storage', { key: 'date_format', newValue: 'dmy', storageArea: localStorage })
      )
    })

    expect(getActiveDateLocale()).toBe('en-GB')
    expect(h.emit).toHaveBeenCalledTimes(1)
  })
})
