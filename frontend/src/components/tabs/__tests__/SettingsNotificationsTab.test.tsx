import { useEffect } from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { SettingsProvider, useSettings } from '@/contexts/SettingsContext'

// EventNotificationsCard, rendered by this tab, reads `useUnitFormat()` for the
// service-reminder lead-distance suffix, and that reaches `useAuth()`, which
// throws without a provider.
vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({ user: null, isAuthenticated: false, defaultUnitPrefs: null }),
}))

vi.mock('@/services/api', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
  },
}))

// The global setup mock (src/__tests__/setup.ts) hands back a brand-new `t`
// function on every useTranslation() call. SettingsNotificationsTab's
// loadSettings is a useCallback keyed on [t], so an ever-changing `t`
// identity re-fires the mount effect on every render — an infinite
// load-settings loop in tests only (real react-i18next memoizes `t`). Pin a
// stable reference here so the component behaves like it does in production.
vi.mock('react-i18next', () => {
  const stableT = (key: string) => key
  return {
    useTranslation: () => ({
      t: stableT,
      i18n: { language: 'en', changeLanguage: () => Promise.resolve() },
    }),
    Trans: ({ children }: { children: React.ReactNode }) => children,
    initReactI18next: { type: '3rdParty', init: () => {} },
  }
})

import api from '@/services/api'
import SettingsNotificationsTab from '../SettingsNotificationsTab'

const mockedApi = vi.mocked(api)

// SettingsNotificationsTab's auto-save only fires once SettingsContext knows
// this tab is the active one (mirrors what pages/Settings.tsx does for the
// real tab switcher).
function ActiveNotificationsTab() {
  const { setCurrentTabId } = useSettings()
  useEffect(() => {
    setCurrentTabId('notifications')
  }, [setCurrentTabId])
  return <SettingsNotificationsTab />
}

function renderTab(): void {
  // The Telegram section's status line is a query.
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <SettingsProvider>
        <ActiveNotificationsTab />
      </SettingsProvider>
    </QueryClientProvider>,
  )
}

const FUEL_STATUS = { state: 'off', error_code: null, description: null, since: '2026-09-23T00:00:00Z' }

/** The settings list for GET /settings; the poller's state for its own URL. */
function answerGet(settings: Array<{ key: string; value: string }>): void {
  mockedApi.get.mockImplementation(async (url: string) =>
    url === '/notifications/telegram/fuel-commands'
      ? { data: FUEL_STATUS }
      : { data: { settings } },
  )
}

describe('SettingsNotificationsTab — DEF-low settings (Task 17)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    answerGet([{ key: 'ntfy_enabled', value: 'true' }])
    mockedApi.post.mockResolvedValue({ data: {} })
  })

  it('defaults notify_def_low to enabled and the threshold to 25 when unset', async () => {
    renderTab()

    await screen.findByText('events.defLow.group')

    expect(screen.getByRole('checkbox', { name: 'events.defLow.label' })).toBeChecked()
    expect(screen.getByDisplayValue('25')).toBeInTheDocument()
  })

  it('changing the threshold and toggling DEF-low off lands in the saved batch payload', async () => {
    renderTab()

    await screen.findByText('events.defLow.group')

    // Change the percent field while the toggle is still on — the field
    // disables itself once the toggle flips off (mirrors the days/miles
    // sibling fields), so order matters here.
    fireEvent.change(screen.getByDisplayValue('25'), { target: { value: '40' } })
    fireEvent.click(screen.getByRole('checkbox', { name: 'events.defLow.label' }))

    // Auto-save is debounced 1s (see SettingsContext.triggerSave).
    await waitFor(() => expect(mockedApi.post).toHaveBeenCalled(), { timeout: 3000 })

    const lastCall = mockedApi.post.mock.calls[mockedApi.post.mock.calls.length - 1]
    const [url, body] = lastCall as [string, { settings: Record<string, string> }]
    expect(url).toBe('/settings/batch')
    expect(body.settings.notify_def_low).toBe('false')
    expect(body.settings.notify_def_low_threshold_percent).toBe('40')
  })
})

describe('SettingsNotificationsTab — Telegram fuel commands', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    answerGet([
          { key: 'telegram_enabled', value: 'true' },
          { key: 'telegram_inbound_enabled', value: 'true' },
        ])
    mockedApi.post.mockResolvedValue({ data: {} })
  })

  it('loads the fuel commands switch and saves it with the rest of Telegram', async () => {
    renderTab()
    fireEvent.click(await screen.findByRole('button', { name: /Telegram/ }))

    const toggle = screen.getByRole('checkbox', { name: 'telegram.fuel.enable' })
    expect(toggle).toBeChecked()
    fireEvent.click(toggle)

    await waitFor(() => expect(mockedApi.post).toHaveBeenCalled(), { timeout: 3000 })
    const [url, body] = mockedApi.post.mock.calls.at(-1) as [string, { settings: Record<string, string> }]
    expect(url).toBe('/settings/batch')
    expect(body.settings.telegram_inbound_enabled).toBe('false')
  })
})

describe('SettingsNotificationsTab — a switch stored as another on word', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedApi.post.mockResolvedValue({ data: {} })
  })

  // Rows written before the writers normalised to "true"/"false" can hold
  // "1"; the backend reads that as on, so the tab must too.
  it('shows ntfy_enabled stored as "1" as on, and offers the event switches', async () => {
    answerGet([{ key: 'ntfy_enabled', value: '1' }])
    renderTab()

    expect(await screen.findByRole('checkbox', { name: 'ntfy.enable' })).toBeChecked()
    // The event card only opens once some service reads as on.
    expect(screen.getByText('events.defLow.group')).toBeInTheDocument()
  })
})
