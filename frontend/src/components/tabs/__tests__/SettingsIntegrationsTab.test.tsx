/**
 * Structural cover for the Integrations tab.
 *
 * Written BEFORE converting the tab's seven hand-rolled
 * `bg-garage-surface rounded-lg border ... p-6` blocks onto `Card` /
 * `CardHeader`, because the file had no test at all: a mechanical refactor of
 * 771 lines with nothing asserting that every section still renders is how a
 * card quietly disappears behind a mis-paired `</div>`.
 *
 * So this asserts the inventory (every section is present, and the two that
 * carry an About sidecar still offer it), plus the provider table's state
 * column, which is a real accessibility fix rather than a cosmetic one: it
 * rendered a bare lucide Check / X with no accessible name, so a screen reader
 * announced an empty cell for every provider.
 */

import { useEffect } from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { SettingsProvider, useSettings } from '@/contexts/SettingsContext'

vi.mock('@/services/api', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))

// Same reason as SettingsSystemTab.test.tsx: the global setup mock hands back a
// fresh `t` per call, which re-fires the load effects forever. Pin one.
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

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({ isAuthenticated: true, isAdmin: true, authMode: 'local', user: {} }),
}))

vi.mock('@/services/livelinkService', () => ({
  livelinkService: {
    getSettings: vi.fn().mockResolvedValue({ enabled: false }),
    getDevices: vi.fn().mockResolvedValue({ total: 3, online_count: 0, devices: [] }),
    getDeviceFirmwareStatus: vi.fn().mockResolvedValue([]),
  },
}))

// Children that fetch on their own; not under test here.
vi.mock('../../settings/WidgetKeysPanel', () => ({ default: () => <div data-testid="widget-keys" /> }))
vi.mock('../../modals/AddProviderModal', () => ({ default: () => null }))
vi.mock('../../modals/EditProviderModal', () => ({ default: () => null }))
vi.mock('../../modals/LiveLinkSettingsModal', () => ({ default: () => null }))

import api from '@/services/api'
import SettingsIntegrationsTab from '../SettingsIntegrationsTab'

const mockedApi = vi.mocked(api)

const PROVIDERS = [
  {
    name: 'tomtom',
    display_name: 'TomTom Places API',
    enabled: true,
    is_default: false,
    api_usage: 0,
    api_limit: 2500,
    priority: 1,
  },
  {
    name: 'google',
    display_name: 'Google Places',
    enabled: false,
    is_default: false,
    api_usage: 0,
    api_limit: null,
    priority: 2,
  },
]

function ActiveIntegrationsTab() {
  const { setCurrentTabId } = useSettings()
  useEffect(() => {
    setCurrentTabId('integrations')
  }, [setCurrentTabId])
  return <SettingsIntegrationsTab />
}

function renderTab(): void {
  render(
    <SettingsProvider>
      <ActiveIntegrationsTab />
    </SettingsProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  mockedApi.get.mockImplementation((url: string) => {
    if (url === '/settings/poi-providers') {
      return Promise.resolve({ data: { providers: PROVIDERS } })
    }
    return Promise.resolve({ data: { settings: [] } })
  })
})

describe('SettingsIntegrationsTab', () => {
  it('renders every integration section', async () => {
    renderTab()

    // One assertion per card. If a refactor drops or nests one wrongly, the
    // specific name says which.
    for (const key of [
      'integrations.webhooks',
      'integrations.telegramInbound',
      'integrations.llmSection',
      'integrations.nhtsa',
      'integrations.carComplaints',
      'integrations.livelink',
      'integrations.shopFinder',
    ]) {
      expect(await screen.findByText(key), key).toBeInTheDocument()
    }

    // The API keys panel is a separate component, mounted at the top.
    expect(screen.getByTestId('widget-keys')).toBeInTheDocument()
  })

  it('keeps the About sidecar trigger on the two cards that document themselves', async () => {
    renderTab()

    expect(
      await screen.findByRole('button', { name: 'integrations.aboutCarComplaints' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'integrations.aboutLiveLink' }),
    ).toBeInTheDocument()
  })

  it('names the enabled state of each provider in text, not only as an icon', async () => {
    renderTab()

    await waitFor(() => {
      expect(screen.getByText('TomTom Places API')).toBeInTheDocument()
    })

    // Both rows must carry a readable state. The retired Check / X icons had no
    // accessible name, so this assertion is false against that version.
    expect(screen.getByText('integrations.statusActive')).toBeInTheDocument()
    expect(screen.getByText('integrations.statusInactive')).toBeInTheDocument()
  })
})
