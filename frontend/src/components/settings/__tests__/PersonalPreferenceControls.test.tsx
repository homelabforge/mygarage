/**
 * Time and date format, language, currency and dashboard order: each person's own
 * display choices, now in Quick Settings. With an account they save to it (`PUT /auth/me`); without
 * one (auth mode none) they live in this browser's localStorage. A failed save
 * puts the previous choice back.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const h = vi.hoisted(() => ({
  isAuthenticated: true,
  user: { time_format: '12h', language: 'en', currency_code: 'USD', dashboard_sort: 'name' } as Record<
    string,
    string | number
  > | null,
  refreshUser: vi.fn(),
  changeLanguage: vi.fn(),
  language: 'en',
}))

vi.mock('@/services/api', () => ({ default: { put: vi.fn() } }))

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({ isAuthenticated: h.isAuthenticated, user: h.user, refreshUser: h.refreshUser }),
}))

vi.mock('react-i18next', () => {
  const t = (key: string): string => key
  const i18n = {
    get language() {
      return h.language
    },
    changeLanguage: (lang: string) => h.changeLanguage(lang),
  }
  return {
    useTranslation: () => ({ t, i18n }),
    Trans: ({ children }: { children: React.ReactNode }) => children,
    initReactI18next: { type: '3rdParty', init: () => {} },
  }
})

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import api from '@/services/api'
import TimeFormatControl from '../TimeFormatControl'
import DateFormatControl from '../DateFormatControl'
import LanguageControl from '../LanguageControl'
import CurrencyControl from '../CurrencyControl'
import DashboardSortControl from '../DashboardSortControl'
import { readSortPick, rememberSortPick } from '@/utils/dashboardSort'

const mockedPut = vi.mocked(api.put)

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  sessionStorage.clear()
  h.isAuthenticated = true
  h.user = { time_format: '12h', language: 'en', currency_code: 'USD', dashboard_sort: 'name' }
  h.refreshUser = vi.fn().mockResolvedValue(undefined)
  h.changeLanguage = vi.fn().mockResolvedValue(undefined)
  h.language = 'en'
  mockedPut.mockResolvedValue({ data: {} })
})

const pressed = (name: string): string | null =>
  screen.getByRole('button', { name }).getAttribute('aria-pressed')

describe('TimeFormatControl', () => {
  it('saves the choice to the account', async () => {
    render(<TimeFormatControl />)
    expect(pressed('timeFormat.twelveHour')).toBe('true')

    await userEvent.click(screen.getByRole('button', { name: 'timeFormat.twentyFourHour' }))

    expect(mockedPut).toHaveBeenCalledWith('/auth/me', { time_format: '24h' })
    expect(h.refreshUser).toHaveBeenCalled()
    expect(pressed('timeFormat.twentyFourHour')).toBe('true')
  })

  it('keeps the choice in this browser when there is no account', async () => {
    h.isAuthenticated = false
    h.user = null
    const keys: (string | null)[] = []
    const listen = (event: Event): void => {
      keys.push((event as StorageEvent).key)
    }
    window.addEventListener('storage', listen)
    render(<TimeFormatControl />)

    await userEvent.click(screen.getByRole('button', { name: 'timeFormat.twentyFourHour' }))
    window.removeEventListener('storage', listen)

    expect(localStorage.getItem('time_format')).toBe('24h')
    expect(mockedPut).not.toHaveBeenCalled()
    // Announced with its key: a keyless event also makes the unit-preference
    // store re-read and every unit consumer on the page re-render.
    expect(keys).toEqual(['time_format'])
  })

  it('announces the save as a real storage event would, so storage-syncing listeners keep it', async () => {
    h.isAuthenticated = false
    h.user = null
    const events: StorageEvent[] = []
    const listen = (event: Event): void => {
      events.push(event as StorageEvent)
    }
    window.addEventListener('storage', listen)
    render(<TimeFormatControl />)

    await userEvent.click(screen.getByRole('button', { name: 'timeFormat.twentyFourHour' }))
    window.removeEventListener('storage', listen)

    // Without these, TanStack Query Devtools' storage sync reads the event as
    // "another tab removed this key" and deletes the value just saved.
    expect(events).toHaveLength(1)
    expect(events[0].newValue).toBe('24h')
    expect(events[0].storageArea).toBe(localStorage)
    expect(localStorage.getItem('time_format')).toBe('24h')
  })

  it('puts the previous choice back when the save fails', async () => {
    mockedPut.mockRejectedValue(new Error('down'))
    render(<TimeFormatControl />)

    await userEvent.click(screen.getByRole('button', { name: 'timeFormat.twentyFourHour' }))

    await waitFor(() => expect(pressed('timeFormat.twelveHour')).toBe('true'))
  })
})

describe('DateFormatControl', () => {
  it('shows month-first by default and saves day-first to the account', async () => {
    render(<DateFormatControl />)
    expect(pressed('dateFormat.monthFirst')).toBe('true')

    await userEvent.click(screen.getByRole('button', { name: 'dateFormat.dayFirst' }))

    expect(mockedPut).toHaveBeenCalledWith('/auth/me', { date_format: 'dmy' })
    expect(h.refreshUser).toHaveBeenCalled()
    expect(pressed('dateFormat.dayFirst')).toBe('true')
  })

  it('shows the saved choice', () => {
    h.user = { ...h.user, date_format: 'dmy' }
    render(<DateFormatControl />)
    expect(pressed('dateFormat.dayFirst')).toBe('true')
  })

  it('keeps the choice in this browser when there is no account', async () => {
    h.isAuthenticated = false
    h.user = null
    render(<DateFormatControl />)

    await userEvent.click(screen.getByRole('button', { name: 'dateFormat.dayFirst' }))

    expect(localStorage.getItem('date_format')).toBe('dmy')
    expect(mockedPut).not.toHaveBeenCalled()
  })

  it('puts the previous choice back when the save fails', async () => {
    mockedPut.mockRejectedValue(new Error('down'))
    render(<DateFormatControl />)

    await userEvent.click(screen.getByRole('button', { name: 'dateFormat.dayFirst' }))

    await waitFor(() => expect(pressed('dateFormat.monthFirst')).toBe('true'))
  })

  it('is hidden for a language whose dates are day-first anyway', () => {
    h.language = 'de'
    const { container } = render(<DateFormatControl />)
    expect(container).toBeEmptyDOMElement()
  })
})

describe('LanguageControl', () => {
  it('switches the language at once and saves it to the account', async () => {
    render(<LanguageControl />)

    await userEvent.selectOptions(screen.getByLabelText('language.label'), 'pl')

    expect(h.changeLanguage).toHaveBeenCalledWith('pl')
    expect(mockedPut).toHaveBeenCalledWith('/auth/me', { language: 'pl' })
    expect(screen.getByLabelText('language.label')).toHaveValue('pl')
  })

  it('keeps the language in this browser when there is no account', async () => {
    h.isAuthenticated = false
    h.user = null
    render(<LanguageControl />)

    await userEvent.selectOptions(screen.getByLabelText('language.label'), 'de')

    expect(localStorage.getItem('i18nextLng')).toBe('de')
    expect(mockedPut).not.toHaveBeenCalled()
  })

  it('switches back when the save fails', async () => {
    mockedPut.mockRejectedValue(new Error('down'))
    render(<LanguageControl />)

    await userEvent.selectOptions(screen.getByLabelText('language.label'), 'pl')

    await waitFor(() => expect(screen.getByLabelText('language.label')).toHaveValue('en'))
    expect(h.changeLanguage).toHaveBeenLastCalledWith('en')
  })
})

describe('CurrencyControl', () => {
  it('asks in place before changing, then saves to the account', async () => {
    render(<CurrencyControl />)

    await userEvent.selectOptions(screen.getByLabelText('currency.label'), 'EUR')

    // Nothing saved yet, and the question is not a full-screen overlay: a
    // drawer cannot host one.
    expect(mockedPut).not.toHaveBeenCalled()
    expect(screen.getByText('currency.confirmMessage').closest('.fixed')).toBeNull()

    await userEvent.click(screen.getByRole('button', { name: 'currency.confirmAction' }))

    expect(mockedPut).toHaveBeenCalledWith('/auth/me', { currency_code: 'EUR' })
    expect(screen.getByLabelText('currency.label')).toHaveValue('EUR')
    expect(screen.queryByText('currency.confirmMessage')).toBeNull()
  })

  it('changes nothing when the question is cancelled', async () => {
    render(<CurrencyControl />)

    await userEvent.selectOptions(screen.getByLabelText('currency.label'), 'EUR')
    await userEvent.click(screen.getByRole('button', { name: 'common:cancel' }))

    expect(mockedPut).not.toHaveBeenCalled()
    expect(screen.getByLabelText('currency.label')).toHaveValue('USD')
  })

  it('keeps the currency in this browser when there is no account', async () => {
    h.isAuthenticated = false
    h.user = null
    render(<CurrencyControl />)

    await userEvent.selectOptions(screen.getByLabelText('currency.label'), 'EUR')
    await userEvent.click(screen.getByRole('button', { name: 'currency.confirmAction' }))

    expect(localStorage.getItem('currency_code')).toBe('EUR')
    expect(mockedPut).not.toHaveBeenCalled()
  })

  it('puts the previous currency back when the save fails', async () => {
    mockedPut.mockRejectedValue(new Error('down'))
    render(<CurrencyControl />)

    await userEvent.selectOptions(screen.getByLabelText('currency.label'), 'EUR')
    await userEvent.click(screen.getByRole('button', { name: 'currency.confirmAction' }))

    await waitFor(() => expect(screen.getByLabelText('currency.label')).toHaveValue('USD'))
  })
})

describe('DashboardSortControl', () => {
  const select = (): HTMLElement => screen.getByLabelText('dashboardSort.label')

  it('shows the saved default and saves a new one to the account', async () => {
    h.user = { ...h.user, dashboard_sort: 'year-old' }
    render(<DashboardSortControl />)
    expect(select()).toHaveValue('year-old')

    await userEvent.selectOptions(select(), 'maintenance')

    expect(mockedPut).toHaveBeenCalledWith('/auth/me', { dashboard_sort: 'maintenance' })
    expect(h.refreshUser).toHaveBeenCalled()
    expect(select()).toHaveValue('maintenance')
  })

  it('offers exactly the orders the dashboard menu offers', () => {
    render(<DashboardSortControl />)
    const values = Array.from(select().querySelectorAll('option')).map((o) => o.value)
    expect(values).toEqual(['name', 'year-new', 'year-old', 'maintenance'])
  })

  it('shows Name when the account holds an order the app no longer offers', () => {
    h.user = { ...h.user, dashboard_sort: 'by-mileage' }
    render(<DashboardSortControl />)
    expect(select()).toHaveValue('name')
  })

  it("drops this tab's menu pick, so the dashboard opens on the new default", async () => {
    h.user = { ...h.user, id: 7 }
    rememberSortPick(7, { sort: 'year-new', over: 'name' })
    render(<DashboardSortControl />)

    await userEvent.selectOptions(select(), 'maintenance')

    await waitFor(() => expect(readSortPick(7)).toBeNull())
  })

  it('keeps the default in this browser when there is no account', async () => {
    h.isAuthenticated = false
    h.user = null
    const keys: (string | null)[] = []
    const listen = (event: Event): void => {
      keys.push((event as StorageEvent).key)
    }
    window.addEventListener('storage', listen)
    render(<DashboardSortControl />)

    await userEvent.selectOptions(select(), 'year-new')
    window.removeEventListener('storage', listen)

    expect(localStorage.getItem('dashboard_sort')).toBe('year-new')
    expect(mockedPut).not.toHaveBeenCalled()
    expect(keys).toEqual(['dashboard_sort'])
    expect(select()).toHaveValue('year-new')
  })

  it('puts the previous default back, and keeps the menu pick, when the save fails', async () => {
    mockedPut.mockRejectedValue(new Error('down'))
    h.user = { ...h.user, id: 7 }
    rememberSortPick(7, { sort: 'year-new', over: 'name' })
    render(<DashboardSortControl />)

    await userEvent.selectOptions(select(), 'maintenance')

    await waitFor(() => expect(select()).toHaveValue('name'))
    expect(readSortPick(7)).toEqual({ sort: 'year-new', over: 'name' })
  })
})
