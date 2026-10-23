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

// Children with their own data fetching; not under test here. The SSO modal
// keeps its props, so a test can call the onSaved the tab hands it.
type OIDCModalProps = { onSaved: () => Promise<unknown> | void }
const oidcModal = vi.hoisted(() => ({ props: null as OIDCModalProps | null }))
vi.mock('@/components/ArchivedVehiclesList', () => ({ default: () => null }))
vi.mock('@/components/modals/OIDCModal', () => ({
  default: (props: OIDCModalProps) => {
    oidcModal.props = props
    return null
  },
}))
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

// Makes one endpoint fail on top of whatever serveSettings set up.
function failGet(failing: string, error: unknown = new Error('down')): void {
  const served = mockedApi.get.getMockImplementation()
  if (!served) throw new Error('call serveSettings first')
  mockedApi.get.mockImplementation((url: string) => (url === failing ? Promise.reject(error) : served(url)))
}

// The Switch button renders before the settings land, disabled. Clicking it then does nothing.
async function clickWhenEnabled(name: string): Promise<void> {
  const button = await screen.findByRole('button', { name })
  await waitFor(() => expect(button).toBeEnabled())
  fireEvent.click(button)
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
    // Reset, not just clear: a test that fails early leaves its queued Once replies
    // behind, and the next test would get them.
    mockedApi.put.mockReset().mockResolvedValue({ data: {} })
    mockedApi.post.mockReset().mockResolvedValue({ data: {} })
    confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
  })
  afterEach(() => {
    confirmSpy.mockRestore()
  })

  it('to SSO: enables OIDC first, then saves the mode, then re-reads auth', async () => {
    serveSettings('none')
    renderTab()
    fireEvent.click(await screen.findByRole('button', { name: /auth\.oidc/ }))
    await clickWhenEnabled('auth.switchToOidc')

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

  it("the SSO switch's PUT leaves out the GET-only client_secret_unreadable flag", async () => {
    serveSettings('none', true, { client_secret_unreadable: true })
    renderTab()
    fireEvent.click(await screen.findByRole('button', { name: /auth\.oidc/ }))
    await clickWhenEnabled('auth.switchToOidc')

    await waitFor(() => expect(refreshUser).toHaveBeenCalledTimes(1))
    expect(mockedApi.put).toHaveBeenCalledWith(
      '/auth/oidc/config/admin',
      expect.objectContaining({ enabled: true, client_secret: '********' }),
    )
    expect(mockedApi.put.mock.calls[0][1]).not.toHaveProperty('client_secret_unreadable')
  })

  it('away from SSO: saves the mode first, then turns OIDC off', async () => {
    serveSettings('oidc')
    renderTab()
    fireEvent.click(await screen.findByRole('button', { name: /auth\.local/ }))
    await clickWhenEnabled('auth.switchToLocal')

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
    await clickWhenEnabled('auth.switchToNone')

    expect(confirmSpy).toHaveBeenCalledWith('auth.confirmNone')
    expect(mockedApi.post).not.toHaveBeenCalled()
    expect(mockedApi.put).not.toHaveBeenCalled()
  })

  it('Switch to SSO stays off until an issuer URL and client ID are saved', async () => {
    serveSettings('none', true, { issuer_url: '', client_id: '' })
    renderTab()
    fireEvent.click(await screen.findByRole('button', { name: /auth\.oidc/ }))

    // The hint needs the loaded config, so the button below is off for the right reason.
    expect(await screen.findByText('auth.oidcNotReady')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'auth.switchToOidc' })).toBeDisabled()
  })

  it('warns that the first person to register becomes admin when nobody has an account', async () => {
    serveSettings('none', false)
    renderTab()
    fireEvent.click(await screen.findByRole('button', { name: /auth\.local/ }))
    await clickWhenEnabled('auth.switchToLocal')

    await waitFor(() => expect(confirmSpy).toHaveBeenCalledWith('auth.confirmLocalFirstUser'))
  })

  it('tells a fresh install to register if SSO fails, since nobody has a password yet', async () => {
    serveSettings('none', false)
    renderTab()
    fireEvent.click(await screen.findByRole('button', { name: /auth\.oidc/ }))
    await clickWhenEnabled('auth.switchToOidc')

    await waitFor(() => expect(confirmSpy).toHaveBeenCalledWith('auth.confirmOidcFirstUser|Rauthy'))
  })

  it('a mode write that never landed: shows the saved mode and still re-reads auth', async () => {
    mockedApi.post.mockRejectedValue(new Error('boom'))
    serveSettings('local')
    renderTab()
    fireEvent.click(await screen.findByRole('button', { name: /auth\.none/ }))
    await clickWhenEnabled('auth.switchToNone')

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
    await clickWhenEnabled('auth.switchToLocal')

    await waitFor(() => expect(refreshUser).toHaveBeenCalledTimes(1))
    expect(await screen.findByRole('button', { name: /auth\.local/ })).toHaveTextContent('auth.current')
    await waitFor(() => expect(toast.warning).toHaveBeenCalledWith('auth.ssoStillOn'))
    expect(toast.error).not.toHaveBeenCalled()
  })

  it('to SSO, SSO went on but the mode write failed: turns SSO back off from the re-read config', async () => {
    serveSettings('local')
    mockedApi.put.mockImplementationOnce(() => {
      // The scopes are new, so a rollback built from the click-time config shows up.
      serveSettings('local', true, { enabled: true, scopes: 'openid email' })
      return Promise.resolve({ data: {} })
    })
    mockedApi.post.mockRejectedValue(new Error('boom'))
    renderTab()
    fireEvent.click(await screen.findByRole('button', { name: /auth\.oidc/ }))
    await clickWhenEnabled('auth.switchToOidc')

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('auth.switchFailed'))
    expect(mockedApi.put).toHaveBeenCalledTimes(2)
    const rollback = mockedApi.put.mock.calls[1]
    expect(rollback[0]).toBe('/auth/oidc/config/admin')
    expect(rollback[1]).toEqual(expect.objectContaining({ enabled: false, scopes: 'openid email' }))
    expect(rollback[1]).not.toHaveProperty('redirect_uri')
    const rollbackOrder = mockedApi.put.mock.invocationCallOrder[1]
    expect(mockedApi.post.mock.invocationCallOrder[0]).toBeLessThan(rollbackOrder)
    // And the card re-reads the SSO config after the rollback.
    const configReads = mockedApi.get.mock.calls.flatMap(([url], i) =>
      url === '/auth/oidc/config/admin' ? [mockedApi.get.mock.invocationCallOrder[i]] : [],
    )
    expect(Math.max(...configReads)).toBeGreaterThan(rollbackOrder)
  })

  it('to SSO, the mode write failed and so did the rollback: says the sign-in page still offers SSO', async () => {
    serveSettings('local')
    mockedApi.put
      .mockImplementationOnce(() => {
        serveSettings('local', true, { enabled: true })
        return Promise.resolve({ data: {} })
      })
      .mockRejectedValueOnce(new Error('still down'))
    mockedApi.post.mockRejectedValue(new Error('boom'))
    renderTab()
    fireEvent.click(await screen.findByRole('button', { name: /auth\.oidc/ }))
    await clickWhenEnabled('auth.switchToOidc')

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('auth.ssoLeftOn'))
    expect(mockedApi.put).toHaveBeenCalledTimes(2)
    expect(toast.error).not.toHaveBeenCalledWith('auth.switchFailed')
  })

  it('to SSO, the enable committed but its reply was lost: still turns SSO back off', async () => {
    serveSettings('local')
    mockedApi.put.mockImplementationOnce(() => {
      serveSettings('local', true, { enabled: true }) // committed server-side
      return Promise.reject(new Error('network'))
    })
    renderTab()
    fireEvent.click(await screen.findByRole('button', { name: /auth\.oidc/ }))
    await clickWhenEnabled('auth.switchToOidc')

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('auth.switchFailed'))
    expect(mockedApi.post).not.toHaveBeenCalled()
    expect(mockedApi.put).toHaveBeenCalledTimes(2)
    expect(mockedApi.put.mock.calls[1][1]).toEqual(expect.objectContaining({ enabled: false }))
  })

  it('to SSO, the enable itself failed: nothing to roll back', async () => {
    serveSettings('local')
    mockedApi.put.mockRejectedValueOnce(new Error('boom'))
    renderTab()
    fireEvent.click(await screen.findByRole('button', { name: /auth\.oidc/ }))
    await clickWhenEnabled('auth.switchToOidc')

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('auth.switchFailed'))
    expect(mockedApi.post).not.toHaveBeenCalled()
    expect(mockedApi.put).toHaveBeenCalledTimes(1)
  })

  it('to SSO, both writes landed: SSO stays on', async () => {
    serveSettings('local')
    mockedApi.put.mockImplementationOnce(() => {
      serveSettings('local', true, { enabled: true })
      return Promise.resolve({ data: {} })
    })
    mockedApi.post.mockImplementationOnce(() => {
      serveSettings('oidc')
      return Promise.resolve({ data: {} })
    })
    renderTab()
    fireEvent.click(await screen.findByRole('button', { name: /auth\.oidc/ }))
    await clickWhenEnabled('auth.switchToOidc')

    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('auth.switched'))
    expect(mockedApi.put).toHaveBeenCalledTimes(1)
    expect(toast.error).not.toHaveBeenCalled()
  })

  // Documents the unknown-state branch. Dropping `now !== null` won't compile, so no kill check.
  it('to SSO from local, the mode write failed and the re-read failed too: no rollback on an unknown state', async () => {
    serveSettings('local')
    mockedApi.put.mockImplementationOnce(() => {
      serveSettings('local', true, { enabled: true })
      return Promise.resolve({ data: {} })
    })
    mockedApi.post.mockRejectedValue(new Error('boom'))
    refreshUser.mockImplementationOnce(async () => {
      failGet('/settings')
    })
    renderTab()
    fireEvent.click(await screen.findByRole('button', { name: /auth\.oidc/ }))
    await clickWhenEnabled('auth.switchToOidc')

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('auth.switchFailed'))
    expect(mockedApi.put).toHaveBeenCalledTimes(1)
  })

  it('to SSO with SSO already on and the mode write failing: leaves SSO on, since this switch did not turn it on', async () => {
    serveSettings('local', true, { enabled: true })
    mockedApi.post.mockRejectedValue(new Error('boom'))
    renderTab()
    fireEvent.click(await screen.findByRole('button', { name: /auth\.oidc/ }))
    await clickWhenEnabled('auth.switchToOidc')

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('auth.switchFailed'))
    expect(mockedApi.put).toHaveBeenCalledTimes(1)
    expect(mockedApi.put).toHaveBeenCalledWith(
      '/auth/oidc/config/admin',
      expect.objectContaining({ enabled: true }),
    )
  })

  it('the mode write committed but its reply was lost: shows the new mode and re-reads auth', async () => {
    serveSettings('local')
    mockedApi.post.mockImplementation(() => {
      serveSettings('none') // committed server-side
      return Promise.reject(new Error('network'))
    })
    renderTab()
    fireEvent.click(await screen.findByRole('button', { name: /auth\.none/ }))
    await clickWhenEnabled('auth.switchToNone')

    await waitFor(() => expect(refreshUser).toHaveBeenCalledTimes(1))
    expect(await screen.findByRole('button', { name: /auth\.none/ })).toHaveTextContent('auth.current')
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('auth.switched'))
  })

  it('turning sign-in on from none reports no failure when /settings then 401s', async () => {
    serveSettings('none')
    // What AuthContext does for real: the refresh flips the api to local mode,
    // and this browser has no session there, so the admin-only GET 401s.
    refreshUser.mockImplementationOnce(async () => {
      failGet('/settings', { isAxiosError: true, response: { status: 401 } })
    })
    renderTab()
    fireEvent.click(await screen.findByRole('button', { name: /auth\.local/ }))
    await clickWhenEnabled('auth.switchToLocal')

    expect(await screen.findByText('common:errors.generic')).toBeInTheDocument()
    expect(mockedApi.post).toHaveBeenCalledWith('/settings/batch', { settings: { auth_mode: 'local' } })
    expect(toast.error).not.toHaveBeenCalled()
    expect(toast.success).not.toHaveBeenCalled()
  })

  it('with the SSO config unreadable, sign-in can still be turned off', async () => {
    serveSettings('local')
    failGet('/auth/oidc/config/admin')
    renderTab()
    await waitFor(() => expect(mockedApi.get).toHaveBeenCalledWith('/auth/oidc/config/admin'))
    fireEvent.click(await screen.findByRole('button', { name: /auth\.none/ }))
    await clickWhenEnabled('auth.switchToNone')

    await waitFor(() => expect(refreshUser).toHaveBeenCalledTimes(1))
    expect(mockedApi.post).toHaveBeenCalledWith('/settings/batch', { settings: { auth_mode: 'none' } })
    expect(mockedApi.put).not.toHaveBeenCalled()
  })

  it('with the SSO config unreadable, the OIDC tab does not point at a dead Configure button', async () => {
    serveSettings('none')
    failGet('/auth/oidc/config/admin')
    renderTab()
    await waitFor(() => expect(mockedApi.get).toHaveBeenCalledWith('/auth/oidc/config/admin'))
    fireEvent.click(await screen.findByRole('button', { name: /auth\.oidc/ }))

    expect(await screen.findByRole('button', { name: 'auth.configureOIDC' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'auth.switchToOidc' })).toBeDisabled()
    expect(screen.queryByText('auth.oidcNotReady')).not.toBeInTheDocument()
  })

  it('an account count that never loaded gets the SSO confirm that assumes accounts exist', async () => {
    serveSettings('none')
    failGet('/auth/users/count')
    renderTab()
    await waitFor(() => expect(mockedApi.get).toHaveBeenCalledWith('/auth/users/count'))
    fireEvent.click(await screen.findByRole('button', { name: /auth\.oidc/ }))
    await clickWhenEnabled('auth.switchToOidc')

    await waitFor(() => expect(confirmSpy).toHaveBeenCalledWith('auth.confirmOidc|Rauthy'))
  })

  it('a failed settings load leaves Switch off, since the saved mode is unknown', async () => {
    serveSettings('oidc')
    failGet('/settings')
    renderTab()
    await screen.findByText('common:errors.generic')
    fireEvent.click(screen.getByRole('button', { name: /auth\.local/ }))

    expect(await screen.findByRole('button', { name: 'auth.switchToLocal' })).toBeDisabled()
  })
})

describe('SettingsSystemTab: the SSO modal waits for the re-read', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    oidcModal.props = null
  })

  it("onSaved settles only once the saved config is back, so Switch can't act on the old one", async () => {
    serveSettings('oidc')
    renderTab()
    await waitFor(() => expect(oidcModal.props).not.toBeNull())

    // Hold the next config read open.
    const served = mockedApi.get.getMockImplementation()
    if (!served) throw new Error('call serveSettings first')
    const hold: { release: (() => void) | null } = { release: null }
    mockedApi.get.mockImplementation((url: string) =>
      url === '/auth/oidc/config/admin'
        ? new Promise((resolve) => {
            hold.release = () => resolve(served(url))
          })
        : served(url),
    )
    let settled = false
    void Promise.resolve(oidcModal.props?.onSaved()).then(() => {
      settled = true
    })

    await waitFor(() => expect(hold.release).not.toBeNull())
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(settled).toBe(false)
    hold.release?.()
    await waitFor(() => expect(settled).toBe(true))
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
