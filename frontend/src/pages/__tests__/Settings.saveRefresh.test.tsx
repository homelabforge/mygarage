/**
 * A Settings save refreshes what the rest of the app reads off the server:
 * the public settings (every reader of the shared query, and what AuthContext
 * derives from them) and, for an admin, the secrets banner. All without a
 * reload, and a non-admin still never asks for the admin-only status.
 *
 * Real AuthProvider, real query cache, real Settings page; only the System tab
 * is a stand-in that registers a save handler.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { useEffect, type ReactElement } from 'react'
import { screen, waitFor, fireEvent } from '@testing-library/react'
import { renderWithQueryClient } from '@/__tests__/queryClient'
import { AuthProvider, useAuth } from '@/contexts/AuthContext'
import { usePublicSettings } from '@/hooks/queries/usePublicSettings'

type Row = { key: string; value: string | null }

const h = vi.hoisted(() => ({
  publicRows: [] as { key: string; value: string | null }[],
  unreadable: [] as string[],
  isAdmin: true,
  save: vi.fn(),
  get: vi.fn(),
}))

vi.mock('@/services/api', () => ({
  default: { get: h.get, post: vi.fn() },
  setCSRFToken: vi.fn(),
  getCSRFToken: vi.fn(),
  clearCSRFToken: vi.fn(),
  setApiAuthMode: vi.fn(),
}))
vi.mock('sonner', () => ({
  toast: { loading: vi.fn(() => 'toast'), success: vi.fn(), error: vi.fn() },
}))

vi.mock('../../components/tabs/SettingsSystemTab', async () => {
  const { useSettings } = await import('@/contexts/SettingsContext')
  return {
    default: function FakeSystemTab(): ReactElement {
      const { registerSaveHandler, unregisterSaveHandler, triggerSave } = useSettings()
      useEffect(() => {
        registerSaveHandler('system', h.save)
        return () => unregisterSaveHandler('system')
      }, [registerSaveHandler, unregisterSaveHandler])
      return <button onClick={triggerSave}>fake save</button>
    },
  }
})
vi.mock('../../components/tabs/SettingsFilesTab', () => ({ default: () => null }))
vi.mock('../../components/tabs/SettingsIntegrationsTab', () => ({ default: () => null }))
vi.mock('../../components/tabs/SettingsNotificationsTab', () => ({ default: () => null }))
vi.mock('../../components/tabs/SettingsBackupTab', () => ({ default: () => null }))

import { toast } from 'sonner'
import Settings from '../Settings'

const PUBLIC_URL = '/settings/public'
const STATUS_URL = '/settings/secrets/status'

const calls = (url: string): number => h.get.mock.calls.filter(([u]) => u === url).length

function Readers(): ReactElement {
  const values = usePublicSettings()
  const { defaultCountry } = useAuth()
  return (
    <>
      <span data-testid="reader">{String(values.family_friends_enabled ?? 'unset')}</span>
      <span data-testid="auth-country">{String(defaultCountry)}</span>
    </>
  )
}

function rows(ff: string, country: string): Row[] {
  return [
    { key: 'auth_mode', value: 'local' },
    { key: 'family_friends_enabled', value: ff },
    { key: 'default_country', value: country },
  ]
}

/** The app mounts Settings behind ProtectedRoute, which waits for the auth load. */
function SettingsWhenLoaded(): ReactElement | null {
  const { loading } = useAuth()
  return loading ? null : <Settings />
}

function renderPage(): void {
  renderWithQueryClient(
    <AuthProvider>
      <Readers />
      <SettingsWhenLoaded />
    </AuthProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  h.publicRows = rows('false', 'US')
  h.unreadable = ['gotify_token']
  h.isAdmin = true
  // The "server" changes when the tab saves, like a POST /settings/batch would.
  h.save.mockImplementation(async () => {
    h.publicRows = rows('true', 'GB')
    h.unreadable = []
  })
  h.get.mockImplementation((url: string) => {
    if (url === PUBLIC_URL) return Promise.resolve({ data: { settings: h.publicRows } })
    if (url === '/auth/me') {
      return Promise.resolve({ data: { id: 1, username: 'alice', is_admin: h.isAdmin } })
    }
    if (url === STATUS_URL) {
      return Promise.resolve({ data: { keyring: 'ok', unreadable_keys: h.unreadable } })
    }
    return Promise.reject(new Error(`unexpected ${url}`))
  })
})

describe('Settings save refresh', () => {
  it('refetches public settings for every reader and AuthContext, and clears the banner', async () => {
    renderPage()

    await waitFor(() => expect(screen.getByTestId('auth-country')).toHaveTextContent('US'))
    expect(screen.getByTestId('reader')).toHaveTextContent('false')
    expect(await screen.findByRole('alert')).toBeInTheDocument()
    const publicBefore = calls(PUBLIC_URL)

    fireEvent.click(screen.getByRole('button', { name: 'fake save' }))

    await waitFor(() => expect(h.save).toHaveBeenCalledTimes(1), { timeout: 3000 })
    await waitFor(() => expect(screen.getByTestId('auth-country')).toHaveTextContent('GB'))
    expect(screen.getByTestId('reader')).toHaveTextContent('true')
    expect(calls(PUBLIC_URL)).toBe(publicBefore + 1)
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
    expect(calls(STATUS_URL)).toBe(2)
    expect(toast.success).toHaveBeenCalledTimes(1)
  })

  it('a non-admin save refreshes public settings and never asks for the secrets status', async () => {
    h.isAdmin = false
    renderPage()

    await waitFor(() => expect(screen.getByTestId('auth-country')).toHaveTextContent('US'))
    const publicBefore = calls(PUBLIC_URL)

    fireEvent.click(screen.getByRole('button', { name: 'fake save' }))

    await waitFor(() => expect(screen.getByTestId('auth-country')).toHaveTextContent('GB'), {
      timeout: 3000,
    })
    expect(screen.getByTestId('reader')).toHaveTextContent('true')
    expect(calls(PUBLIC_URL)).toBe(publicBefore + 1)
    expect(calls(STATUS_URL)).toBe(0)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})
