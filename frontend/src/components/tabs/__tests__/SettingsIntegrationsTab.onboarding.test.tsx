/**
 * Deletion-gate assertion 1, through the real entry point: with no MQTT device
 * at all, the LiveLink card still offers a way to create one.
 *
 * A preset-backed tab exists only once its device does, and MqttSourcesCard
 * (deleted in the same change as this test) was the only other place a
 * generic MQTT device could be created or a preset applied. So this renders
 * the REAL LiveLinkIntegrationsCard and the REAL AddSourceDrawer inside the
 * real settings tab; a test of AddSourceDrawer alone could not show that the
 * card reaches it.
 */
import { useEffect } from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { SettingsProvider, useSettings } from '@/contexts/SettingsContext'

vi.mock('@/services/api', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))

// Same as SettingsIntegrationsTab.test.tsx: the global mock hands back a fresh
// `t` per call, which re-fires the tab's load effects forever. Pin one.
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

// The LiveLink card renders only for an admin.
vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({ isAuthenticated: true, isAdmin: true, authMode: 'local', user: {} }),
}))

const BUILT_IN = ['wican', 'torque', 'broker'].map((id) => ({
  id,
  label: id,
  kind: id === 'broker' ? null : id,
  status: 'off',
  reason: 'not_configured',
  description: null,
  device_count: 0,
  online_count: 0,
  linked_count: 0,
  firmware_updates: 0,
}))

vi.mock('@/services/livelinkService', () => ({
  livelinkService: {
    // The strip: built-in tabs only, no device tab of any kind.
    getIntegrations: () => Promise.resolve({ tabs: BUILT_IN }),
    listPresets: () =>
      Promise.resolve([
        { name: 'mopeka', title: 'Mopeka', description: 'Mopeka Pro Check propane tank sensors.', kind: 'generic_mqtt', readings: [] },
      ]),
  },
}))
vi.mock('@/services/vehicleService', () => ({
  default: { list: () => Promise.resolve({ vehicles: [], total: 0 }) },
  vehicleService: { list: () => Promise.resolve({ vehicles: [], total: 0 }) },
}))

// Other cards, and fetchers not under test.
vi.mock('../../settings/WidgetKeysPanel', () => ({ default: () => null }))
vi.mock('../../modals/AddProviderModal', () => ({ default: () => null }))
vi.mock('../../modals/EditProviderModal', () => ({ default: () => null }))

import api from '@/services/api'
import SettingsIntegrationsTab from '../SettingsIntegrationsTab'

function ActiveIntegrationsTab() {
  const { setCurrentTabId } = useSettings()
  useEffect(() => {
    setCurrentTabId('integrations')
  }, [setCurrentTabId])
  return <SettingsIntegrationsTab />
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api).get.mockImplementation((url: string) =>
    Promise.resolve({ data: url === '/settings/poi-providers' ? { providers: [] } : { settings: [] } }),
  )
})

describe('Adding a source with no devices at all', () => {
  it('reaches the preset catalog and the blank-device form from the card', async () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <SettingsProvider>
          <ActiveIntegrationsTab />
        </SettingsProvider>
      </QueryClientProvider>,
    )

    // The card has loaded its strip: no device tab exists.
    expect(await screen.findByRole('tab', { name: 'wican' })).toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: 'Mopeka' })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'integrations.addSource' }))

    expect(await screen.findByText('Mopeka')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'integrations.addSensor' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'integrations.mqttCreateDevice' })).toBeInTheDocument()
  })
})
