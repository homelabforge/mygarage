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

describe('the LLM card (#211)', () => {
  // The one toggle on this tab with a privacy consequence: the description
  // that says images leave the server must be under it, and it must save.
  it('offers document reading as a third toggle and saves its flag', async () => {
    renderTab()

    const toggle = await screen.findByRole('checkbox', { name: 'integrations.enableLlmDocuments' })
    expect(screen.getByText('integrations.enableLlmDocumentsDesc')).toBeInTheDocument()
    // The vision model field waits for the toggle: a text-only setup has no use for it.
    expect(screen.queryByLabelText('integrations.llmVisionModel')).not.toBeInTheDocument()

    fireEvent.click(toggle)

    expect(await screen.findByLabelText('integrations.llmVisionModel')).toBeInTheDocument()
    await waitFor(() => expect(mockedApi.post).toHaveBeenCalled(), { timeout: 3000 })
    const [url, body] = mockedApi.post.mock.calls.at(-1) as [string, { settings: Record<string, string> }]
    expect(url).toBe('/settings/batch')
    expect(body.settings.llm_document_reading_enabled).toBe('true')
    expect(body.settings).toHaveProperty('llm_vision_model')
    expect(body.settings).toHaveProperty('llm_provider_preset')
  })

  it('fills the base URL from a preset and never a model name', async () => {
    renderTab()
    const preset = (await screen.findByLabelText('integrations.llmPreset')) as HTMLSelectElement
    expect(preset.options).toHaveLength(4)
    // Every field but the toggles is inert while all three features are off.
    expect(preset).toBeDisabled()
    fireEvent.click(screen.getByRole('checkbox', { name: 'integrations.enableLlmDocuments' }))
    await waitFor(() => expect(preset).not.toBeDisabled())

    fireEvent.change(preset, { target: { value: 'openrouter' } })

    expect(screen.getByLabelText('integrations.llmBaseUrl')).toHaveValue('https://openrouter.ai/api/v1')
    // The model stays whatever it was: a preset must not pick a paid model.
    expect(screen.getByLabelText('integrations.llmModel')).toHaveValue('llama3.2')

    fireEvent.change(preset, { target: { value: 'custom' } })
    expect(screen.getByLabelText('integrations.llmBaseUrl')).toHaveValue('https://openrouter.ai/api/v1')
  })

  it('saves, then tests the stored settings, and reports both checks', async () => {
    mockedApi.post.mockImplementation((url: string) => {
      if (url === '/settings/test/llm') {
        return Promise.resolve({
          data: {
            valid: true,
            message: 'Text model OK; vision model OK',
            text_ok: true,
            vision_ok: true,
            model: 'llama3.2',
            vision_model: 'llava',
          },
        })
      }
      return Promise.resolve({ data: {} })
    })
    renderTab()
    const button = await screen.findByRole('button', { name: 'integrations.llmTest' })
    expect(button).toBeDisabled()
    fireEvent.click(screen.getByRole('checkbox', { name: 'integrations.enableLlmDocuments' }))
    await waitFor(() => expect(button).not.toBeDisabled())

    fireEvent.click(button)

    expect(await screen.findByText('integrations.llmTestVisionOk')).toBeInTheDocument()
    const urls = mockedApi.post.mock.calls.map(([url]) => url as string)
    const save = urls.indexOf('/settings/batch')
    const test = urls.lastIndexOf('/settings/test/llm')
    expect(save).toBeGreaterThanOrEqual(0)
    expect(test).toBeGreaterThan(save)
  })

  it('shows the endpoint failure the server reports', async () => {
    mockedApi.post.mockImplementation((url: string) => {
      if (url === '/settings/test/llm') {
        return Promise.resolve({
          data: {
            valid: false,
            message: 'LLM endpoint request failed',
            text_ok: false,
            vision_ok: null,
            model: 'llama3.2',
            vision_model: 'llama3.2',
          },
        })
      }
      return Promise.resolve({ data: {} })
    })
    renderTab()
    fireEvent.click(await screen.findByRole('checkbox', { name: 'integrations.enableLlmReceipt' }))
    const button = screen.getByRole('button', { name: 'integrations.llmTest' })
    await waitFor(() => expect(button).not.toBeDisabled())

    fireEvent.click(button)

    expect(await screen.findByText('integrations.llmTestFailed')).toBeInTheDocument()
  })
})
