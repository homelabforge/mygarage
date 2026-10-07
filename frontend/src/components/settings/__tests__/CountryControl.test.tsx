/**
 * The country control saves to the account when signed in (`PUT /auth/me`),
 * to this browser otherwise, and offers "Not set" to clear it.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

const h = vi.hoisted(() => ({
  isAuthenticated: true,
  user: { country: null as string | null },
  refreshUser: vi.fn(),
}))

vi.mock('@/services/api', () => ({ default: { put: vi.fn() } }))

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({
    isAuthenticated: h.isAuthenticated,
    user: h.isAuthenticated ? h.user : null,
    refreshUser: h.refreshUser,
    defaultCountry: null,
  }),
}))

vi.mock('react-i18next', () => {
  const t = (key: string): string => key
  const i18n = { language: 'en', changeLanguage: vi.fn() }
  return {
    useTranslation: () => ({ t, i18n }),
    Trans: ({ children }: { children: React.ReactNode }) => children,
    initReactI18next: { type: '3rdParty', init: () => {} },
  }
})

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import api from '@/services/api'
import CountryControl from '../CountryControl'

const mockedPut = vi.mocked(api.put)

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  h.isAuthenticated = true
  h.user = { country: null }
  h.refreshUser = vi.fn().mockResolvedValue(undefined)
  mockedPut.mockResolvedValue({ data: {} })
})

describe('CountryControl', () => {
  it('lists every country plus "Not set", opening on the stored code', () => {
    h.user = { country: 'FR' }
    render(<CountryControl />)
    const select = screen.getByLabelText('country.label') as HTMLSelectElement
    expect(select.value).toBe('FR')
    expect(select.options.length).toBe(250)
    expect(select.options[0].value).toBe('')
    expect(select.options[0].textContent).toBe('country.none')
  })

  it('saves the choice to the account', async () => {
    render(<CountryControl />)
    const select = screen.getByLabelText('country.label') as HTMLSelectElement
    fireEvent.change(select, { target: { value: 'LU' } })
    await waitFor(() => expect(mockedPut).toHaveBeenCalledWith('/auth/me', { country: 'LU' }))
    expect(h.refreshUser).toHaveBeenCalled()
    expect(select.value).toBe('LU')
  })

  it('keeps the choice in this browser when there is no account', async () => {
    h.isAuthenticated = false
    render(<CountryControl />)
    const select = screen.getByLabelText('country.label') as HTMLSelectElement
    fireEvent.change(select, { target: { value: 'DE' } })
    await waitFor(() => expect(localStorage.getItem('country')).toBe('DE'))
    expect(mockedPut).not.toHaveBeenCalled()
  })

  it('puts the stored code back when the save fails', async () => {
    h.user = { country: 'FR' }
    mockedPut.mockRejectedValueOnce(new Error('nope'))
    render(<CountryControl />)
    const select = screen.getByLabelText('country.label') as HTMLSelectElement
    fireEvent.change(select, { target: { value: 'IT' } })
    await waitFor(() => expect(mockedPut).toHaveBeenCalled())
    await waitFor(() => expect(select.value).toBe('FR'))
  })
})
