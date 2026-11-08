/**
 * The Settings page warns when secret settings can't be read (D3a, R1-M2).
 *
 * The banner reads GET /settings/secrets/status, which is admin-only on the
 * server, while the /settings route itself is open to everyone signed in. So it
 * fetches and shows only for someone who can manage the instance: an admin, or
 * the single user when auth is off (`isAdmin` alone is false there). A
 * signed-in non-admin makes no request at all, rather than collecting a 403.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderWithQueryClient } from '@/__tests__/queryClient'
import { screen, waitFor, within } from '@testing-library/react'

const h = vi.hoisted(() => ({
  isAdmin: true,
  authMode: 'local',
  get: vi.fn(),
}))

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({ isAdmin: h.isAdmin, authMode: h.authMode, refreshPublicSettings: vi.fn() }),
}))
vi.mock('@/services/api', () => ({ default: { get: h.get } }))
vi.mock('../../components/tabs/SettingsSystemTab', () => ({ default: () => null }))
vi.mock('../../components/tabs/SettingsFilesTab', () => ({ default: () => null }))
vi.mock('../../components/tabs/SettingsIntegrationsTab', () => ({ default: () => null }))
vi.mock('../../components/tabs/SettingsNotificationsTab', () => ({ default: () => null }))
vi.mock('../../components/tabs/SettingsBackupTab', () => ({ default: () => null }))

import Settings from '../Settings'

const STATUS_URL = '/settings/secrets/status'

function answer(data: {
  keyring: 'ok' | 'unavailable'
  keyring_source?: string
  unreadable_keys: string[]
}): void {
  h.get.mockImplementation((url: string) =>
    url === STATUS_URL ? Promise.resolve({ data }) : Promise.reject(new Error(`unexpected ${url}`)),
  )
}

beforeEach(() => {
  h.isAdmin = true
  h.authMode = 'local'
  h.get.mockReset()
})

describe('Settings secrets banner', () => {
  it('lists the unreadable secrets for an admin', async () => {
    answer({ keyring: 'ok', unreadable_keys: ['gotify_token', 'ntfy_token'] })
    renderWithQueryClient(<Settings />)

    const banner = await screen.findByRole('alert')
    expect(banner).toHaveTextContent('secretsStatus.title')
    expect(banner).toHaveTextContent('secretsStatus.unreadable')
    // Labels, not setting keys (the global mock hands back the label's key).
    expect(banner).toHaveTextContent('secretsStatus.labels.gotifyToken')
    expect(banner).toHaveTextContent('secretsStatus.labels.ntfyToken')
    expect(banner).not.toHaveTextContent('gotify_token')
    expect(banner).not.toHaveTextContent('secretsStatus.keyringUnavailable')
    expect(h.get).toHaveBeenCalledWith(STATUS_URL)
  })

  it('shows for the single user when auth is off, where isAdmin is false', async () => {
    h.isAdmin = false
    h.authMode = 'none'
    answer({ keyring: 'unavailable', unreadable_keys: [] })
    renderWithQueryClient(<Settings />)

    const banner = await screen.findByRole('alert')
    expect(banner).toHaveTextContent('secretsStatus.keyringUnavailable')
    expect(banner).not.toHaveTextContent('secretsStatus.unreadable')
    expect(h.get).toHaveBeenCalledWith(STATUS_URL)
  })

  it('makes no request and shows nothing for a signed-in non-admin', async () => {
    h.isAdmin = false
    answer({ keyring: 'unavailable', unreadable_keys: ['gotify_token'] })
    renderWithQueryClient(<Settings />)

    // Let any effect that would have fetched run and settle.
    await waitFor(() => expect(screen.getAllByRole('tab')).toHaveLength(2))
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(h.get).not.toHaveBeenCalled()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('shows nothing when everything reads', async () => {
    answer({ keyring: 'ok', unreadable_keys: [] })
    renderWithQueryClient(<Settings />)

    await waitFor(() => expect(h.get).toHaveBeenCalledWith(STATUS_URL))
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('shows nothing when the status request fails', async () => {
    h.get.mockRejectedValue(new Error('network down'))
    renderWithQueryClient(<Settings />)

    await waitFor(() => expect(h.get).toHaveBeenCalledWith(STATUS_URL))
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  // B2-21: a broken env var wins over the data dir, so the banner names it.
  it.each([
    ['env', 'secretsStatus.keyringUnavailableEnv'],
    ['env_file', 'secretsStatus.keyringUnavailableEnvFile'],
    ['data_dir', 'secretsStatus.keyringUnavailable'],
  ])('with the %s source broken it shows %s', async (source, text) => {
    answer({ keyring: 'unavailable', keyring_source: source, unreadable_keys: [] })
    renderWithQueryClient(<Settings />)

    const banner = await screen.findByRole('alert')
    // Exact matches: each key is a prefix of the next.
    expect(within(banner).getByText(text)).toBeInTheDocument()
    if (source !== 'data_dir') {
      expect(within(banner).queryByText('secretsStatus.keyringUnavailable')).toBeNull()
    }
  })
})
