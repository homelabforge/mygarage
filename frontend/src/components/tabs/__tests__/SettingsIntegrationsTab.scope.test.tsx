/**
 * What a non-admin gets on the Integrations tab: their own widget keys.
 *
 * Every other card here (LLM, VIN decoding, recalls, inbound webhooks,
 * LiveLink) is an instance setting, admin-only on the server. A non-admin used
 * to get the whole tab, its load failing into an error banner and every edit
 * silently failing to save.
 */
import { useEffect } from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { SettingsProvider, useSettings } from '@/contexts/SettingsContext'

const h = vi.hoisted(() => ({ isAdmin: false, authMode: 'local' }))

vi.mock('@/services/api', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))

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
  useAuth: () => ({ isAuthenticated: true, isAdmin: h.isAdmin, authMode: h.authMode, user: {} }),
}))

vi.mock('@/services/livelinkService', () => ({
  livelinkService: {
    getSettings: vi.fn().mockResolvedValue({ enabled: false }),
    getDevices: vi.fn().mockResolvedValue({ total: 0, online_count: 0, devices: [] }),
    getDeviceFirmwareStatus: vi.fn().mockResolvedValue([]),
  },
}))
vi.mock('../../settings/WidgetKeysPanel', () => ({ default: () => <div data-testid="widget-keys" /> }))
vi.mock('../../livelink/LiveLinkIntegrationsCard', () => ({ default: () => null }))
vi.mock('../../livelink/settings/LiveLinkSettingsDrawers', () => ({ default: () => null }))
vi.mock('../../livelink/AddSourceDrawer', () => ({ default: () => null }))

import api from '@/services/api'
import SettingsIntegrationsTab from '../SettingsIntegrationsTab'

const mockedApi = vi.mocked(api)

function ActiveIntegrationsTab(): React.ReactElement {
  const { setCurrentTabId } = useSettings()
  useEffect(() => {
    setCurrentTabId('integrations')
  }, [setCurrentTabId])
  return <SettingsIntegrationsTab />
}

function renderTab(): void {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <SettingsProvider>
        <ActiveIntegrationsTab />
      </SettingsProvider>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  h.isAdmin = false
  h.authMode = 'local'
  mockedApi.get.mockResolvedValue({ data: { settings: [] } })
})

describe('SettingsIntegrationsTab: a non-admin', () => {
  it('gets their widget keys and none of the instance cards', async () => {
    renderTab()

    expect(await screen.findByTestId('widget-keys')).toBeInTheDocument()
    expect(screen.queryByText('integrations.llmSection')).toBeNull()
    expect(screen.queryByText('integrations.loadError')).toBeNull()
  })

  it('does not ask for the instance settings', async () => {
    renderTab()
    await screen.findByTestId('widget-keys')

    expect(mockedApi.get).not.toHaveBeenCalledWith('/settings')
  })
})

describe('SettingsIntegrationsTab: an admin', () => {
  it('gets the instance cards too', async () => {
    h.isAdmin = true
    renderTab()

    expect(await screen.findByText('integrations.llmSection')).toBeInTheDocument()
    await waitFor(() => expect(mockedApi.get).toHaveBeenCalledWith('/settings'))
  })
})
