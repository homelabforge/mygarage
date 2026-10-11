import { useEffect } from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
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
// A `provider` option is appended, so a test can check the name made it in.
vi.mock('react-i18next', () => {
  const stableT = (key: string, opts?: Record<string, unknown>) =>
    opts && 'provider' in opts ? `${key}|${String(opts.provider)}` : key
  return {
    useTranslation: () => ({
      t: stableT,
      i18n: { language: 'en', changeLanguage: () => Promise.resolve() },
    }),
    Trans: ({ children }: { children: React.ReactNode }) => children,
    initReactI18next: { type: '3rdParty', init: () => {} },
  }
})

const refreshUser = vi.hoisted(() => vi.fn())
vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({
    isAuthenticated: true,
    isAdmin: true,
    user: { unit_preference: 'imperial', language: 'en', currency_code: 'USD' },
    refreshUser,
    refreshPublicSettings: vi.fn(),
    householdTimeZone: null,
  }),
}))

// SettingsContext uses `loading` and hands its id back to success/error.
vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), loading: vi.fn(() => 'id') },
}))

// Children with their own data fetching; not under test here.
vi.mock('@/components/ArchivedVehiclesList', () => ({ default: () => null }))
vi.mock('@/components/modals/OIDCModal', () => ({ default: () => null }))
vi.mock('@/components/modals/FamilyManagementModal', () => ({ default: () => null }))

import api from '@/services/api'
import { toast } from 'sonner'
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

function serveSettings(mode: string, hasUsers = true, oidc: Partial<Record<string, unknown>> = {}): void {
  mockedApi.get.mockImplementation((url: string) => {
    if (url === '/settings') {
      return Promise.resolve({
        data: { settings: [{ key: 'timezone', value: 'UTC' }, { key: 'auth_mode', value: mode }] },
      })
    }
    if (url === '/auth/oidc/config/admin') {
      return Promise.resolve({
        data: {
          enabled: mode === 'oidc',
          provider_name: 'Rauthy',
          issuer_url: 'https://auth.example.com',
          client_id: 'client-id',
          client_secret: '********',
          redirect_uri: '',
          scopes: 'openid profile email',
          auto_create_users: true,
          admin_group: '',
          username_claim: 'preferred_username',
          email_claim: 'email',
          full_name_claim: 'name',
          ...oidc,
        },
      })
    }
    if (url === '/auth/users/count') return Promise.resolve({ data: { has_users: hasUsers } })
    return Promise.resolve({ data: {} })
  })
}

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

describe('SettingsSystemTab: the local-auth card reads has_users', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('says local auth is configured once anyone has registered', async () => {
    mockedApi.get.mockImplementation((url: string) => {
      if (url === '/settings') {
        return Promise.resolve({ data: { settings: [{ key: 'auth_mode', value: 'local' }] } })
      }
      if (url === '/auth/users/count') return Promise.resolve({ data: { has_users: true } })
      return Promise.resolve({ data: {} })
    })
    renderTab()

    expect(await screen.findByText('auth.localConfigured')).toBeInTheDocument()
  })
})

describe('SettingsSystemTab: the auth tabs only show a panel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('clicking OIDC on a none-mode instance writes nothing, even after the auto-save delay', async () => {
    serveSettings('none')
    renderTab()
    fireEvent.click(await screen.findByRole('button', { name: /auth\.oidc/ }))

    expect(await screen.findByRole('button', { name: 'auth.configureOIDC' })).toBeInTheDocument()
    // Past the 1 s auto-save, the same real wait this file's failed-load test uses.
    await new Promise((resolve) => setTimeout(resolve, 1300))
    expect(mockedApi.post).not.toHaveBeenCalled()
    expect(mockedApi.put).not.toHaveBeenCalled()
  })

  it('marks the saved mode as current', async () => {
    serveSettings('local')
    renderTab()

    const local = await screen.findByRole('button', { name: /auth\.local/ })
    expect(local).toHaveTextContent('auth.current')
  })
})

describe('SettingsSystemTab: switching the mode', () => {
  let confirmSpy: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    vi.clearAllMocks()
    mockedApi.put.mockResolvedValue({ data: {} })
    mockedApi.post.mockResolvedValue({ data: {} })
    confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
  })
  afterEach(() => {
    confirmSpy.mockRestore()
  })

  it('to SSO: enables OIDC first, then saves the mode, then re-reads auth', async () => {
    serveSettings('none')
    renderTab()
    fireEvent.click(await screen.findByRole('button', { name: /auth\.oidc/ }))
    fireEvent.click(await screen.findByRole('button', { name: 'auth.switchToOidc' }))

    await waitFor(() => expect(refreshUser).toHaveBeenCalledTimes(1))
    expect(confirmSpy).toHaveBeenCalledWith('auth.confirmOidc|Rauthy')
    const putOrder = mockedApi.put.mock.invocationCallOrder[0]
    const postOrder = mockedApi.post.mock.invocationCallOrder[0]
    expect(putOrder).toBeLessThan(postOrder)
    expect(mockedApi.put).toHaveBeenCalledWith(
      '/auth/oidc/config/admin',
      expect.objectContaining({ enabled: true, issuer_url: 'https://auth.example.com' }),
    )
    expect(mockedApi.post).toHaveBeenCalledWith('/settings/batch', { settings: { auth_mode: 'oidc' } })
    expect(mockedApi.put.mock.calls[0][1]).not.toHaveProperty('redirect_uri')
  })

  it('away from SSO: saves the mode first, then turns OIDC off', async () => {
    serveSettings('oidc')
    renderTab()
    fireEvent.click(await screen.findByRole('button', { name: /auth\.local/ }))
    fireEvent.click(await screen.findByRole('button', { name: 'auth.switchToLocal' }))

    await waitFor(() => expect(refreshUser).toHaveBeenCalledTimes(1))
    expect(mockedApi.post.mock.invocationCallOrder[0]).toBeLessThan(
      mockedApi.put.mock.invocationCallOrder[0],
    )
    expect(mockedApi.put).toHaveBeenCalledWith(
      '/auth/oidc/config/admin',
      expect.objectContaining({ enabled: false }),
    )
  })

  it('a cancelled confirm writes nothing', async () => {
    confirmSpy.mockReturnValue(false)
    serveSettings('local')
    renderTab()
    fireEvent.click(await screen.findByRole('button', { name: /auth\.none/ }))
    fireEvent.click(await screen.findByRole('button', { name: 'auth.switchToNone' }))

    expect(confirmSpy).toHaveBeenCalledWith('auth.confirmNone')
    expect(mockedApi.post).not.toHaveBeenCalled()
    expect(mockedApi.put).not.toHaveBeenCalled()
  })

  it('Switch to SSO stays off until an issuer URL and client ID are saved', async () => {
    serveSettings('none', true, { issuer_url: '', client_id: '' })
    renderTab()
    fireEvent.click(await screen.findByRole('button', { name: /auth\.oidc/ }))

    expect(await screen.findByRole('button', { name: 'auth.switchToOidc' })).toBeDisabled()
    expect(screen.getByText('auth.oidcNotReady')).toBeInTheDocument()
  })

  it('warns that the first person to register becomes admin when nobody has an account', async () => {
    serveSettings('none', false)
    renderTab()
    fireEvent.click(await screen.findByRole('button', { name: /auth\.local/ }))
    fireEvent.click(await screen.findByRole('button', { name: 'auth.switchToLocal' }))

    await waitFor(() => expect(confirmSpy).toHaveBeenCalledWith('auth.confirmLocalFirstUser'))
  })

  it('tells a fresh install to register if SSO fails, since nobody has a password yet', async () => {
    serveSettings('none', false)
    renderTab()
    fireEvent.click(await screen.findByRole('button', { name: /auth\.oidc/ }))
    fireEvent.click(await screen.findByRole('button', { name: 'auth.switchToOidc' }))

    await waitFor(() => expect(confirmSpy).toHaveBeenCalledWith('auth.confirmOidcFirstUser|Rauthy'))
  })

  it('a mode write that never landed: shows the saved mode and still re-reads auth', async () => {
    mockedApi.post.mockRejectedValue(new Error('boom'))
    serveSettings('local')
    renderTab()
    fireEvent.click(await screen.findByRole('button', { name: /auth\.none/ }))
    fireEvent.click(await screen.findByRole('button', { name: 'auth.switchToNone' }))

    await waitFor(() => expect(refreshUser).toHaveBeenCalledTimes(1))
    expect(await screen.findByRole('button', { name: /auth\.local/ })).toHaveTextContent('auth.current')
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('auth.switchFailed'))
  })

  it('the mode landed but turning OIDC off failed: shows the new mode and says SSO is still on', async () => {
    serveSettings('oidc')
    mockedApi.post.mockImplementation(() => {
      serveSettings('local', true, { enabled: true }) // mode is local, SSO still on
      return Promise.resolve({ data: {} })
    })
    mockedApi.put.mockRejectedValue(new Error('boom'))
    renderTab()
    fireEvent.click(await screen.findByRole('button', { name: /auth\.local/ }))
    fireEvent.click(await screen.findByRole('button', { name: 'auth.switchToLocal' }))

    await waitFor(() => expect(refreshUser).toHaveBeenCalledTimes(1))
    expect(await screen.findByRole('button', { name: /auth\.local/ })).toHaveTextContent('auth.current')
    await waitFor(() => expect(toast.warning).toHaveBeenCalledWith('auth.ssoStillOn'))
    expect(toast.error).not.toHaveBeenCalled()
  })

  it('the mode write committed but its reply was lost: shows the new mode and re-reads auth', async () => {
    serveSettings('local')
    mockedApi.post.mockImplementation(() => {
      serveSettings('none') // committed server-side
      return Promise.reject(new Error('network'))
    })
    renderTab()
    fireEvent.click(await screen.findByRole('button', { name: /auth\.none/ }))
    fireEvent.click(await screen.findByRole('button', { name: 'auth.switchToNone' }))

    await waitFor(() => expect(refreshUser).toHaveBeenCalledTimes(1))
    expect(await screen.findByRole('button', { name: /auth\.none/ })).toHaveTextContent('auth.current')
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('auth.switched'))
  })
})

describe('SettingsSystemTab: the local panel reads has_users (S1a-13 control)', () => {
  beforeEach(() => vi.clearAllMocks())

  it('describes local auth when nobody has registered yet', async () => {
    serveSettings('local', false)
    renderTab()

    expect(await screen.findByText('auth.localDescription')).toBeInTheDocument()
    expect(screen.queryByText('auth.localConfigured')).not.toBeInTheDocument()
  })
})
