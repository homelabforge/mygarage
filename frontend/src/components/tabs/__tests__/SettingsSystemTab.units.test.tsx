/**
 * The Units card branches on the system the account RESOLVES to, not on the
 * raw stored preference.
 *
 * Migration 093 materialises a UK instance's imperial users as
 * `unit_preference='custom'`. Branching on `unitPreference === 'imperial'`
 * therefore showed them the metric description and removed the US/UK gallon
 * sub-panel entirely, which is their only UI for changing gallon flavour until
 * phase 3 retires it. The two-option toggle itself still shows the raw value
 * (a per-quantity editor is phase 4) and is deliberately not asserted here.
 */
import { useEffect } from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { SettingsProvider, useSettings } from '@/contexts/SettingsContext'
import { IMPERIAL_UNITS, METRIC_UNITS, makeUser, type User } from '@/__tests__/factories'

const h = vi.hoisted(() => ({ user: null as User | null }))

vi.mock('@/services/api', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
  },
}))

// See SettingsSystemTab.test.tsx: the global setup mock returns a fresh `t`
// per call, which re-fires load effects forever. Pin a stable reference.
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
  useAuth: () => ({
    isAuthenticated: true,
    isAdmin: true,
    user: h.user,
    refreshUser: vi.fn(),
  }),
}))

// Children with their own data fetching; not under test here.
vi.mock('@/components/ArchivedVehiclesList', () => ({ default: () => null }))
vi.mock('@/components/modals/OIDCModal', () => ({ default: () => null }))
vi.mock('@/components/modals/FamilyManagementModal', () => ({ default: () => null }))

import api from '@/services/api'
import SettingsSystemTab from '../SettingsSystemTab'

const mockedApi = vi.mocked(api)

function ActiveSystemTab(): React.ReactElement {
  const { setCurrentTabId } = useSettings()
  useEffect(() => {
    setCurrentTabId('system')
  }, [setCurrentTabId])
  return <SettingsSystemTab />
}

function renderTab(): void {
  render(
    <SettingsProvider>
      <ActiveSystemTab />
    </SettingsProvider>,
  )
}

/** The set migration 093 writes into a UK instance's imperial users. */
const UK_IMPERIAL_UNITS = {
  ...IMPERIAL_UNITS,
  volume: 'gal_uk',
  consumption: 'mpg_uk',
  secondary_gallon: 'uk',
} as const

describe('SettingsSystemTab — units card follows the resolved system', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    h.user = null
    mockedApi.get.mockImplementation((url: string) => {
      if (url === '/settings') {
        return Promise.resolve({
          data: { settings: [{ key: 'timezone', value: 'UTC' }] },
        })
      }
      if (url === '/auth/users/count') return Promise.resolve({ data: { count: 2 } })
      if (url === '/dashboard') return Promise.resolve({ data: { total_vehicles: 0 } })
      if (url === '/health') return Promise.resolve({ data: { authenticator_detected: false } })
      return Promise.resolve({ data: {} })
    })
    mockedApi.post.mockResolvedValue({ data: { settings: [], total: 0 } })
    mockedApi.put.mockResolvedValue({ data: {} })
  })

  it('keeps the gallon-standard panel for a custom user resolving to UK gallons', async () => {
    h.user = makeUser({ unit_preference: 'custom', resolved_units: UK_IMPERIAL_UNITS })

    renderTab()

    expect(await screen.findByText('units.gallonStandard')).toBeInTheDocument()
    expect(screen.getByText('units.imperialDescription')).toBeInTheDocument()
    expect(screen.queryByText('units.metricDescription')).not.toBeInTheDocument()
  })

  it('hides the gallon-standard panel for a custom user resolving to litres', async () => {
    h.user = makeUser({ unit_preference: 'custom', resolved_units: METRIC_UNITS })

    renderTab()

    expect(await screen.findByText('units.metricDescription')).toBeInTheDocument()
    expect(screen.queryByText('units.gallonStandard')).not.toBeInTheDocument()
    expect(screen.queryByText('units.imperialDescription')).not.toBeInTheDocument()
  })

  it('still shows the panel for a preset imperial user', async () => {
    h.user = makeUser({ unit_preference: 'imperial', resolved_units: IMPERIAL_UNITS })

    renderTab()

    expect(await screen.findByText('units.gallonStandard')).toBeInTheDocument()
    expect(screen.getByText('units.imperialDescription')).toBeInTheDocument()
  })

  it('still hides the panel for a preset metric user', async () => {
    h.user = makeUser({ unit_preference: 'metric', resolved_units: METRIC_UNITS })

    renderTab()

    await waitFor(() => expect(mockedApi.get).toHaveBeenCalledWith('/settings'))
    expect(await screen.findByText('units.metricDescription')).toBeInTheDocument()
    expect(screen.queryByText('units.gallonStandard')).not.toBeInTheDocument()
  })
})
