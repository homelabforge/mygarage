/**
 * Backup tab, create buttons. The backup preflight refuses a backup with a 503 whose detail says
 * what to fix ("Set MYGARAGE_SETTINGS_KEY ..."). Both create buttons showed a fixed "Failed to
 * create ... backup" instead, so that fix never reached the admin. They show the server's detail
 * now, and the generic text when there is none.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

vi.mock('@/services/api', () => ({
  default: { get: vi.fn(), post: vi.fn(), delete: vi.fn(), defaults: {} },
}))

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({ refreshPublicSettings: vi.fn() }),
}))

vi.mock('@/hooks/useTimeFormat', () => ({
  useTimeFormat: () => ({ timeFormat: '12h' }),
}))

import api from '@/services/api'
import SettingsBackupTab from '../SettingsBackupTab'

const mockedApi = vi.mocked(api)

const REFUSAL =
  'Backups are refused while these secret settings are stored unencrypted: ntfy_token. ' +
  'Set MYGARAGE_SETTINGS_KEY to a valid key, or make the data directory writable so a key ' +
  'can be generated, then try again.'

function httpError(status: number, detail?: string): object {
  return {
    isAxiosError: true,
    message: `Request failed with status code ${status}`,
    response: { status, data: detail === undefined ? {} : { detail } },
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  mockedApi.get.mockImplementation((url: string) => {
    if (url === '/backup/stats') {
      return Promise.resolve({
        data: {
          database: { size_mb: 1, last_modified: '2026-10-02T12:00:00', exists: true, is_sqlite: true },
          settings_backups: { count: 0, total_size_mb: 0 },
          full_backups: { count: 0, total_size_mb: 0 },
          is_sqlite: true,
          restore_pending: null,
        },
      })
    }
    if (url === '/backup/list?backup_type=all') {
      return Promise.resolve({ data: { backups: [] } })
    }
    return Promise.reject(new Error(`unexpected GET ${url}`))
  })
})

describe.each([
  ['settings', 'backup.createSettingsBackup', '/backup/create', 'backup.createSettingsError'],
  ['full', 'backup.createFullBackup', '/backup/create-full', 'backup.createFullError'],
])('SettingsBackupTab create %s backup', (_kind, button, url, generic) => {
  it('shows the preflight 503 detail, which says what to fix', async () => {
    mockedApi.post.mockRejectedValue(httpError(503, REFUSAL))
    render(<SettingsBackupTab />)

    fireEvent.click(await screen.findByRole('button', { name: button }))

    expect(await screen.findByText(REFUSAL)).toBeInTheDocument()
    expect(mockedApi.post).toHaveBeenCalledWith(url)
  })

  it('shows a 403 detail too', async () => {
    mockedApi.post.mockRejectedValue(httpError(403, 'Permission denied: cannot write to backup directory'))
    render(<SettingsBackupTab />)

    fireEvent.click(await screen.findByRole('button', { name: button }))

    expect(await screen.findByText('Permission denied: cannot write to backup directory')).toBeInTheDocument()
  })

  it('keeps the generic text for a server error, whose detail stays hidden', async () => {
    mockedApi.post.mockRejectedValue(httpError(500, 'Traceback (most recent call last)'))
    render(<SettingsBackupTab />)

    fireEvent.click(await screen.findByRole('button', { name: button }))

    expect(await screen.findByText(generic)).toBeInTheDocument()
    expect(screen.queryByText(/Traceback/)).not.toBeInTheDocument()
  })

  it('keeps the generic text when there is no detail', async () => {
    mockedApi.post.mockRejectedValue(httpError(503))
    render(<SettingsBackupTab />)

    fireEvent.click(await screen.findByRole('button', { name: button }))

    expect(await screen.findByText(generic)).toBeInTheDocument()
  })
})
