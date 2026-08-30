import { useEffect } from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
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
  render(
    <SettingsProvider>
      <ActiveNotificationsTab />
    </SettingsProvider>,
  )
}

describe('SettingsNotificationsTab — DEF-low settings (Task 17)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedApi.get.mockResolvedValue({
      data: { settings: [{ key: 'ntfy_enabled', value: 'true' }] },
    })
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
