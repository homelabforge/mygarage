/**
 * The inspection auto-schedule toggle (#211) saves to the account when signed
 * in (`PUT /auth/me`), to this browser otherwise, and is on unless the
 * stored value is the string 'false'.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

const h = vi.hoisted(() => ({
  isAuthenticated: true,
  user: { inspection_auto_schedule: true as boolean },
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
import { toast } from 'sonner'
import InspectionAutoScheduleControl, {
  INSPECTION_AUTO_SCHEDULE_STORAGE_KEY,
  asAutoSchedule,
} from '../InspectionAutoScheduleControl'

const mockedPut = vi.mocked(api.put)

const toggle = (): HTMLInputElement =>
  screen.getByLabelText('inspection.autoSchedule') as HTMLInputElement

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  h.isAuthenticated = true
  h.user = { inspection_auto_schedule: true }
  h.refreshUser = vi.fn().mockResolvedValue(undefined)
  mockedPut.mockResolvedValue({ data: {} })
})

describe('asAutoSchedule', () => {
  it('is on unless the stored value says false', () => {
    expect(asAutoSchedule(null)).toBe(true)
    expect(asAutoSchedule(undefined)).toBe(true)
    expect(asAutoSchedule('true')).toBe(true)
    expect(asAutoSchedule('garbage')).toBe(true)
    expect(asAutoSchedule('false')).toBe(false)
  })
})

describe('InspectionAutoScheduleControl', () => {
  it('opens on the account value', () => {
    h.user = { inspection_auto_schedule: false }
    render(<InspectionAutoScheduleControl />)
    expect(toggle().checked).toBe(false)
  })

  it('saves a change to the account as a string', async () => {
    render(<InspectionAutoScheduleControl />)
    expect(toggle().checked).toBe(true)
    fireEvent.click(toggle())
    await waitFor(() =>
      expect(mockedPut).toHaveBeenCalledWith('/auth/me', { inspection_auto_schedule: 'false' })
    )
    expect(h.refreshUser).toHaveBeenCalled()
    expect(toggle().checked).toBe(false)
    expect(toast.success).toHaveBeenCalledWith('inspection.saved')
  })

  it('puts the stored value back when the save fails', async () => {
    mockedPut.mockRejectedValueOnce(new Error('nope'))
    render(<InspectionAutoScheduleControl />)
    fireEvent.click(toggle())
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('inspection.error'))
    expect(toggle().checked).toBe(true)
  })

  it('saves to this browser when there is no account', async () => {
    h.isAuthenticated = false
    render(<InspectionAutoScheduleControl />)
    expect(toggle().checked).toBe(true)
    fireEvent.click(toggle())
    await waitFor(() =>
      expect(localStorage.getItem(INSPECTION_AUTO_SCHEDULE_STORAGE_KEY)).toBe('false')
    )
    expect(mockedPut).not.toHaveBeenCalled()
    expect(toggle().checked).toBe(false)
  })
})
