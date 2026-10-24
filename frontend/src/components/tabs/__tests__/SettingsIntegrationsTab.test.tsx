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
 * carry an About sidecar still offer it). The Shop Finder provider table moved
 * to Find POI's own sidecar (`components/poi/PoiProvidersDrawer`), tested there.
 */

import { useEffect } from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
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
// Fetches on its own and has its own suite. Exposes refreshKey and the
// settings callback so this suite can test the wiring between the two.
vi.mock('../../livelink/LiveLinkIntegrationsCard', () => ({
  default: ({
    refreshKey,
    onOpenSettings,
    onAddSource,
  }: {
    refreshKey?: number
    onOpenSettings: (tab: { id: string }) => void
    onAddSource?: () => void
  }) => (
    <div data-testid="livelink-integrations" data-refresh={refreshKey}>
      <button onClick={() => onOpenSettings({ id: 'wican' })}>open-source-settings</button>
      {onAddSource ? <button onClick={onAddSource}>open-add-source</button> : null}
    </div>
  ),
}))
// The settings drawers have their own suites. The stub exposes which target
// is open and a way to close it, so this suite can test the wiring.
vi.mock('../../livelink/settings/LiveLinkSettingsDrawers', () => ({
  default: ({
    target,
    onClose,
  }: {
    target: { type: string; tab?: { id: string } } | null
    onClose: () => void
  }) =>
    target ? (
      <div data-testid="settings-drawer" data-target={target.type} data-tab={target.tab?.id}>
        <button onClick={onClose}>close-settings-drawer</button>
      </div>
    ) : null,
}))
// Fetches presets and vehicles on its own; has its own suite.
vi.mock('../../livelink/AddSourceDrawer', () => ({
  default: ({ open, onCreated }: { open: boolean; onCreated: () => void }) =>
    open ? <button onClick={onCreated}>source-created</button> : null,
}))

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
      'integrations.llmSection',
      'integrations.nhtsa',
      'integrations.carComplaints',
      'integrations.livelink',
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

  it('leaves the search providers to Find POI', async () => {
    renderTab()
    await screen.findByText('integrations.livelink')

    expect(screen.queryByText('integrations.shopFinderDesc')).not.toBeInTheDocument()
    expect(screen.queryByText('TomTom Places API')).not.toBeInTheDocument()
    expect(mockedApi.get).not.toHaveBeenCalledWith('/settings/poi-providers')
  })

  it('leaves Telegram fuel commands to Settings > Notifications > Telegram', async () => {
    // Two tabs saving one key would each write back whatever they loaded.
    renderTab()
    fireEvent.click(await screen.findByRole('checkbox', { name: 'integrations.enableCarComplaints' }))

    await waitFor(() => expect(mockedApi.post).toHaveBeenCalled(), { timeout: 3000 })
    const [url, body] = mockedApi.post.mock.calls.at(-1) as [string, { settings: Record<string, string> }]
    expect(url).toBe('/settings/batch')
    expect(body.settings).toHaveProperty('webhook_ingest_token')
    expect(body.settings).not.toHaveProperty('telegram_inbound_enabled')
  })

  // Rows written before the writers normalised to "true"/"false" can hold
  // "1"; the backend reads that as on, so the toggle must too.
  it('shows a switch stored as "1" as on', async () => {
    mockedApi.get.mockImplementation((url: string) =>
      Promise.resolve({
        data: url === '/settings' ? { settings: [{ key: 'llm_receipt_parse_enabled', value: '1' }] } : { settings: [] },
      }),
    )
    renderTab()

    expect(await screen.findByRole('checkbox', { name: 'integrations.enableLlmReceipt' })).toBeChecked()
    // The LLM fields follow the switch, so they are open too.
    expect(screen.getByLabelText('integrations.llmModel')).toBeEnabled()
  })

  describe('the NHTSA recalls URL', () => {
    // The backend adds /recallsByVehicle itself, so the form's default has to be
    // the base. The full endpoint got saved and fetched with the path twice.
    const RECALLS_BASE = 'https://api.nhtsa.gov/recalls'

    it("saves the backend's base when nothing is stored", async () => {
      renderTab()
      fireEvent.click(await screen.findByRole('checkbox', { name: 'integrations.enableCarComplaints' }))

      await waitFor(() => expect(mockedApi.post).toHaveBeenCalled(), { timeout: 3000 })
      const [url, body] = mockedApi.post.mock.calls.at(-1) as [string, { settings: Record<string, string> }]
      expect(url).toBe('/settings/batch')
      expect(body.settings.nhtsa_recalls_api_url).toBe(RECALLS_BASE)
    })

    it('suggests the same base as its placeholder', async () => {
      renderTab()

      expect(await screen.findByLabelText('integrationsTab.nhtsaRecallsApiUrl')).toHaveAttribute(
        'placeholder',
        RECALLS_BASE,
      )
    })
  })

  it('describes LiveLink by its sources, not by one vendor', async () => {
    // A new key rather than a rewrite of livelinkDesc: six locales translate
    // the old WiCAN-specific text, and rewriting its English value would leave
    // every one of them silently stale.
    renderTab()

    expect(await screen.findByText('integrations.livelinkSourcesDesc')).toBeInTheDocument()
    expect(screen.queryByText('integrations.livelinkDesc')).not.toBeInTheDocument()
  })

  it('mounts the integrations strip inside the LiveLink card', async () => {
    renderTab()

    expect(await screen.findByTestId('livelink-integrations')).toBeInTheDocument()
    // The old body's Configure button is gone; the strip's per-source
    // Settings button replaces it.
    expect(screen.queryByText('integrations.configureLiveLink')).not.toBeInTheDocument()
  })

  it("opens a tab's own settings drawer from its Settings button", async () => {
    // Each source's settings, and nothing else: there is no all-in-one modal.
    renderTab()

    fireEvent.click(await screen.findByRole('button', { name: 'open-source-settings' }))

    const drawer = await screen.findByTestId('settings-drawer')
    expect(drawer).toHaveAttribute('data-target', 'tab')
    expect(drawer).toHaveAttribute('data-tab', 'wican')
  })

  it('opens the Add-source drawer from the strip', async () => {
    renderTab()

    fireEvent.click(await screen.findByRole('button', { name: 'open-add-source' }))

    expect(await screen.findByRole('button', { name: 'source-created' })).toBeInTheDocument()
  })

  it('a created source refreshes the strip', async () => {
    // So the new tab appears without a reload.
    renderTab()

    const strip = await screen.findByTestId('livelink-integrations')
    const before = Number(strip.dataset.refresh)

    fireEvent.click(screen.getByRole('button', { name: 'open-add-source' }))
    fireEvent.click(await screen.findByRole('button', { name: 'source-created' }))

    await waitFor(() =>
      expect(Number(screen.getByTestId('livelink-integrations').dataset.refresh)).toBe(before + 1),
    )
  })

  it('opens the global LiveLink settings from the gear', async () => {
    // Retention, alerts and the master switch belong to no single source.
    renderTab()

    fireEvent.click(await screen.findByRole('button', { name: 'integrations.livelinkGeneral' }))

    expect(await screen.findByTestId('settings-drawer')).toHaveAttribute('data-target', 'general')
  })

  it('refetches the strip when a settings drawer closes', async () => {
    renderTab()

    const strip = await screen.findByTestId('livelink-integrations')
    const before = Number(strip.dataset.refresh)
    fireEvent.click(screen.getByRole('button', { name: 'integrations.livelinkGeneral' }))
    fireEvent.click(await screen.findByRole('button', { name: 'close-settings-drawer' }))

    await waitFor(() =>
      expect(Number(screen.getByTestId('livelink-integrations').dataset.refresh)).toBe(before + 1),
    )
    expect(screen.queryByTestId('settings-drawer')).not.toBeInTheDocument()
  })
})
