import { useEffect } from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { SettingsProvider, useSettings } from '@/contexts/SettingsContext'

vi.mock('@/services/api', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
  },
}))

// See SettingsNotificationsTab.test.tsx: the global setup mock returns a fresh
// `t` per call, which re-fires load effects forever. Pin a stable reference.
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
    user: { unit_preference: 'imperial', language: 'en', currency_code: 'USD' },
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

function ActiveSystemTab() {
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

/**
 * The OIDC admin PUT is a separate call from the settings batch that carries
 * auth_mode, and saving is auto-triggered by any edit on this tab. If the PUT
 * fires unconditionally, an unrelated edit is coupled to it — the exact shape
 * of the bug that stranded auth_mode at "none".
 */
describe('SettingsSystemTab — OIDC config is only written when OIDC changed', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedApi.get.mockImplementation((url: string) => {
      if (url === '/settings') {
        return Promise.resolve({
          data: {
            settings: [
              { key: 'timezone', value: 'UTC' },
              { key: 'auth_mode', value: 'oidc' },
            ],
          },
        })
      }
      if (url === '/auth/oidc/config/admin') {
        return Promise.resolve({
          data: {
            enabled: true,
            provider_name: 'Rauthy',
            issuer_url: 'https://auth.example.com',
            client_id: 'client-id',
            client_secret: '********',
            scopes: 'openid profile email',
            auto_create_users: true,
            admin_group: '',
            username_claim: 'preferred_username',
            email_claim: 'email',
            full_name_claim: 'name',
          },
        })
      }
      if (url === '/auth/users/count') return Promise.resolve({ data: { has_users: true } })
      if (url === '/dashboard') return Promise.resolve({ data: { total_vehicles: 0 } })
      if (url === '/health') return Promise.resolve({ data: { authenticator_detected: false } })
      return Promise.resolve({ data: {} })
    })
    mockedApi.post.mockResolvedValue({ data: { settings: [], total: 0 } })
    mockedApi.put.mockResolvedValue({ data: {} })
  })

  it('does not PUT the OIDC config when only a non-OIDC setting changed', async () => {
    renderTab()
    await waitFor(() => expect(mockedApi.get).toHaveBeenCalledWith('/settings'))

    const timezone = await screen.findByDisplayValue('UTC')
    fireEvent.change(timezone, { target: { value: 'America/Chicago' } })

    await waitFor(
      () =>
        expect(mockedApi.post).toHaveBeenCalledWith(
          '/settings/batch',
          expect.objectContaining({
            settings: expect.objectContaining({ timezone: 'America/Chicago' }),
          }),
        ),
      { timeout: 3000 },
    )

    expect(mockedApi.put).not.toHaveBeenCalledWith(
      '/auth/oidc/config/admin',
      expect.anything(),
    )
  })

  it('PUTs the OIDC config before the settings batch when the auth mode changes', async () => {
    renderTab()
    await waitFor(() => expect(mockedApi.get).toHaveBeenCalledWith('/settings'))

    // Switching modes sets oidc_enabled alongside auth_mode, so OIDC is dirty.
    fireEvent.click(await screen.findByText('auth.local'))

    await waitFor(
      () =>
        expect(mockedApi.put).toHaveBeenCalledWith(
          '/auth/oidc/config/admin',
          expect.objectContaining({ enabled: false }),
        ),
      { timeout: 3000 },
    )
    await waitFor(
      () =>
        expect(mockedApi.post).toHaveBeenCalledWith(
          '/settings/batch',
          expect.objectContaining({
            settings: expect.objectContaining({ auth_mode: 'local' }),
          }),
        ),
      { timeout: 3000 },
    )

    // Config must land before the mode flips, or OIDC is enabled against
    // settings that never saved.
    const putOrder = mockedApi.put.mock.invocationCallOrder[0]
    const postOrder = mockedApi.post.mock.invocationCallOrder[0]
    expect(putOrder).toBeLessThan(postOrder)
  })
})

describe('SettingsSystemTab: a save sends only what changed', () => {
  const OIDC_ADMIN = {
    enabled: false, provider_name: '', issuer_url: '', client_id: '', client_secret: '',
    scopes: 'openid profile email', auto_create_users: true, admin_group: '',
    username_claim: 'preferred_username', email_claim: 'email', full_name_claim: 'name',
  }

  const mockSettings = (settings: { key: string; value: string }[] | Error) => {
    mockedApi.get.mockImplementation((url: string) => {
      if (url === '/settings') {
        return settings instanceof Error ? Promise.reject(settings) : Promise.resolve({ data: { settings } })
      }
      if (url === '/auth/oidc/config/admin') return Promise.resolve({ data: OIDC_ADMIN })
      if (url === '/auth/users/count') return Promise.resolve({ data: { has_users: true } })
      if (url === '/dashboard') return Promise.resolve({ data: { total_vehicles: 0 } })
      if (url === '/health') return Promise.resolve({ data: { authenticator_detected: false } })
      return Promise.resolve({ data: {} })
    })
  }

  const timezoneSelect = () => document.getElementById('timezone') as HTMLSelectElement

  beforeEach(() => {
    vi.clearAllMocks()
    mockedApi.post.mockResolvedValue({ data: { settings: [], total: 0 } })
    mockedApi.put.mockResolvedValue({ data: {} })
  })

  it('with no zone stored, shows the server default instead of freezing it in', async () => {
    mockSettings([
      { key: 'auth_mode', value: 'local' },
      { key: 'effective_timezone', value: 'America/Denver' },
    ])
    renderTab()
    await waitFor(() => expect(timezoneSelect()).toBeInTheDocument())
    await waitFor(() => expect(mockedApi.get).toHaveBeenCalledWith('/auth/users/count'))
    expect(timezoneSelect().value).toBe('')
    expect(timezoneSelect().options[0].value).toBe('')
    // Nothing stored, so the zone in effect IS the server default.
    expect(timezoneSelect().options[0].textContent).toBe('timezone.serverDefaultZone')
  })

  it('changing one setting posts only that one', async () => {
    mockSettings([
      { key: 'auth_mode', value: 'local' },
      { key: 'family_friends_enabled', value: 'false' },
      { key: 'effective_timezone', value: 'America/Denver' },
    ])
    renderTab()
    const toggle = await screen.findByLabelText('garageSections.familyFriends')
    await waitFor(() => expect(mockedApi.get).toHaveBeenCalledWith('/auth/users/count'))
    fireEvent.click(toggle)
    await waitFor(() => expect(mockedApi.post).toHaveBeenCalled(), { timeout: 3000 })
    expect(mockedApi.post).toHaveBeenCalledWith('/settings/batch', {
      settings: { family_friends_enabled: 'true' },
    })
    expect(mockedApi.put).not.toHaveBeenCalled()
  })

  it('choosing Server default on a stored zone saves an empty zone', async () => {
    mockSettings([
      { key: 'timezone', value: 'America/Chicago' },
      { key: 'auth_mode', value: 'local' },
      { key: 'effective_timezone', value: 'America/Chicago' },
    ])
    renderTab()
    await screen.findByDisplayValue('America/Chicago')
    fireEvent.change(timezoneSelect(), { target: { value: '' } })
    await waitFor(() => expect(mockedApi.post).toHaveBeenCalled(), { timeout: 3000 })
    expect(mockedApi.post).toHaveBeenCalledWith('/settings/batch', { settings: { timezone: '' } })
    // Chicago was the stored zone, not the server's default, so the option
    // must not name it now that it's cleared.
    await waitFor(() => expect(timezoneSelect().options[0].textContent).toBe('timezone.serverDefault'))
  })

  it('a failed load posts nothing, even when a save fires', async () => {
    mockSettings(new Error('settings down'))
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    function SaveButton() {
      const { triggerSave } = useSettings()
      return <button onClick={triggerSave}>trigger-save</button>
    }
    render(
      <QueryClientProvider client={queryClient}>
        <SettingsProvider>
          <ActiveSystemTab />
          <SaveButton />
        </SettingsProvider>
      </QueryClientProvider>,
    )
    await screen.findByText('common:errors.generic')
    fireEvent.click(screen.getByText('trigger-save'))
    await new Promise((resolve) => setTimeout(resolve, 1300))
    expect(mockedApi.post).not.toHaveBeenCalled()
    expect(mockedApi.put).not.toHaveBeenCalled()
  })
})
