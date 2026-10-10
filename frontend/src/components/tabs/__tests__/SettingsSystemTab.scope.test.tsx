/**
 * Settings > System holds what applies to the whole instance, for admins.
 *
 * Each person's own display preferences (units, time format, language,
 * currency) moved to Quick Settings. A non-admin used to get the whole tab:
 * the timezone read UTC, switches looked saved and never were (every
 * instance setting is admin-only on the server), and the Authentication card
 * said "None". Now a non-admin sees only the cards that are theirs, and the
 * tab asks the server for nothing it would refuse. With auth off there is one
 * user and no admin, so everything shows, as before.
 */
import { useEffect } from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { SettingsProvider, useSettings } from '@/contexts/SettingsContext'

const h = vi.hoisted(() => ({
  isAdmin: true,
  isAuthenticated: true,
  authMode: 'local',
}))

vi.mock('@/services/api', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
  },
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
  useAuth: () => ({
    isAuthenticated: h.isAuthenticated,
    isAdmin: h.isAdmin,
    authMode: h.authMode,
    publicSettingsLoaded: true,
    user: h.isAuthenticated ? { unit_preference: 'imperial', language: 'en', currency_code: 'USD' } : null,
    refreshUser: vi.fn(),
    refreshPublicSettings: vi.fn(),
    householdTimeZone: null,
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
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={queryClient}>
      <SettingsProvider>
        <ActiveSystemTab />
      </SettingsProvider>
    </QueryClientProvider>,
  )
}

/** The endpoints only an admin may read. */
const ADMIN_READS = ['/settings', '/auth/oidc/config/admin', '/auth/users/count', '/health']

beforeEach(() => {
  vi.clearAllMocks()
  h.isAdmin = true
  h.isAuthenticated = true
  h.authMode = 'local'
  mockedApi.get.mockImplementation((url: string) => {
    if (url === '/settings') {
      return Promise.resolve({ data: { settings: [{ key: 'timezone', value: 'UTC' }] } })
    }
    if (url === '/auth/users/count') return Promise.resolve({ data: { has_users: true } })
    if (url === '/dashboard') return Promise.resolve({ data: { total_vehicles: 0 } })
    if (url === '/health') return Promise.resolve({ data: { authenticator_detected: false } })
    return Promise.resolve({ data: {} })
  })
  mockedApi.post.mockResolvedValue({ data: {} })
  mockedApi.put.mockResolvedValue({ data: {} })
})

describe('SettingsSystemTab: instance settings only', () => {
  it('gives an admin the instance settings, and none of the personal ones', async () => {
    renderTab()

    expect(await screen.findByText('systemConfig.title')).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'units.instanceDefault' })).toBeInTheDocument()

    // Moved to Quick Settings.
    expect(screen.queryByRole('region', { name: 'units.label' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'timeFormat.twelveHour' })).toBeNull()
    expect(screen.queryByText('language.label')).toBeNull()
    expect(screen.queryByText('currency.label')).toBeNull()
  })

  it('has no Debug Mode switch: nothing ever read it', async () => {
    renderTab()
    await screen.findByText('systemConfig.title')

    expect(screen.queryByText('debug.label')).toBeNull()
    expect(screen.queryByRole('checkbox', { name: 'debug.enable' })).toBeNull()
  })

  it('never writes a debug setting when an instance setting saves', async () => {
    renderTab()
    const timezone = await screen.findByDisplayValue('UTC')
    fireEvent.change(timezone, { target: { value: 'America/Chicago' } })

    await waitFor(() => expect(mockedApi.post).toHaveBeenCalledWith('/settings/batch', expect.anything()), {
      timeout: 3000,
    })
    const [, body] = mockedApi.post.mock.calls.at(-1) as [string, { settings: Record<string, string> }]
    expect(body.settings).not.toHaveProperty('debug')
  })
})

describe('SettingsSystemTab: a non-admin', () => {
  beforeEach(() => {
    h.isAdmin = false
  })

  it('sees only the cards that are theirs', async () => {
    renderTab()

    expect(await screen.findByText('mobile.title')).toBeInTheDocument()
    expect(screen.getByText('fuel.title')).toBeInTheDocument()
    expect(screen.getByText('archive.title')).toBeInTheDocument()

    expect(screen.queryByText('systemConfig.title')).toBeNull()
    expect(screen.queryByText('auth.title')).toBeNull()
  })

  it('asks the server for nothing it would refuse', async () => {
    renderTab()
    await screen.findByText('mobile.title')
    await waitFor(() => expect(mockedApi.get).toHaveBeenCalledWith('/dashboard'))

    for (const url of ADMIN_READS) {
      expect(mockedApi.get).not.toHaveBeenCalledWith(url)
    }
  })
})

describe('SettingsSystemTab: auth off', () => {
  it('shows everything to the single user, as before', async () => {
    h.isAdmin = false
    h.isAuthenticated = false
    h.authMode = 'none'
    renderTab()

    expect(await screen.findByText('systemConfig.title')).toBeInTheDocument()
    expect(screen.getByText('auth.title')).toBeInTheDocument()
    expect(mockedApi.get).toHaveBeenCalledWith('/settings')
  })
})
