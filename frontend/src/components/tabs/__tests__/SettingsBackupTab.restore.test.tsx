/**
 * Backup tab, full restore. A full restore is staged and finishes at the next start, so the
 * tab says to restart. "Refresh the page" was wrong: until the restart a refresh shows the
 * current data, and the restore looks like it failed. While a restore is staged the tab says
 * which one and when, and can cancel it. A settings restore changes the public settings now, so
 * it refreshes them; a full restore changes nothing until the restart, so it doesn't.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'

vi.mock('@/services/api', () => ({
  default: { get: vi.fn(), post: vi.fn(), delete: vi.fn(), defaults: {} },
}))

const { refreshPublicSettings } = vi.hoisted(() => ({ refreshPublicSettings: vi.fn() }))

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({ refreshPublicSettings }),
}))

vi.mock('@/hooks/useTimeFormat', () => ({
  useTimeFormat: () => ({ timeFormat: '12h' }),
}))

import api from '@/services/api'
import SettingsBackupTab from '../SettingsBackupTab'

const mockedApi = vi.mocked(api)
const FULL = 'mygarage-full-2026-10-02-120000.tar.gz'
const SETTINGS = 'mygarage-settings-2026-10-02-120000.json'
let pending: { source_backup: string | null; staged_at: string | null } | null = null

beforeEach(() => {
  vi.clearAllMocks()
  refreshPublicSettings.mockResolvedValue(undefined)
  pending = null
  mockedApi.get.mockImplementation((url: string) => {
    if (url === '/backup/stats') {
      return Promise.resolve({
        data: {
          database: { size_mb: 1, last_modified: '2026-10-02T12:00:00', exists: true, is_sqlite: true },
          settings_backups: { count: 0, total_size_mb: 0 },
          full_backups: { count: 1, total_size_mb: 1 },
          is_sqlite: true,
          restore_pending: pending,
        },
      })
    }
    if (url === '/backup/list?backup_type=all') {
      return Promise.resolve({
        data: {
          backups: [
            { filename: FULL, type: 'full', size_mb: 1, created: '2026-10-02T12:00:00', is_safety: false },
            { filename: SETTINGS, type: 'settings', size_mb: 0.01, created: '2026-10-02T12:00:00', is_safety: false },
          ],
        },
      })
    }
    return Promise.reject(new Error(`unexpected GET ${url}`))
  })
  mockedApi.post.mockResolvedValue({
    data: { success: true, message: 'Restore staged. Restart MyGarage to finish.', details: {} },
  })
  vi.spyOn(window, 'confirm').mockReturnValue(true)
})

describe('SettingsBackupTab full restore', () => {
  it('says the restore finishes when MyGarage restarts', async () => {
    render(<SettingsBackupTab />)
    fireEvent.click(await screen.findByTitle('backup.restoreOverwrite'))
    await waitFor(() => expect(mockedApi.post).toHaveBeenCalledWith(`/backup/restore/${FULL}`))
    expect(await screen.findByText('backupTab.fullRestoreStaged')).toBeInTheDocument()
  })

  it('refreshes the public settings after a settings restore, and not after a full one', async () => {
    render(<SettingsBackupTab />)
    fireEvent.click(await screen.findByTitle('backup.restoreOverwrite'))
    expect(await screen.findByText('backupTab.fullRestoreStaged')).toBeInTheDocument()
    expect(refreshPublicSettings).not.toHaveBeenCalled()

    fireEvent.click(screen.getByTitle('backup.restore'))
    await waitFor(() => expect(mockedApi.post).toHaveBeenCalledWith(`/backup/restore/${SETTINGS}`))
    await waitFor(() => expect(refreshPublicSettings).toHaveBeenCalledTimes(1))
  })

  it('says up front that a full restore needs a restart, and shows no notice with nothing staged', async () => {
    render(<SettingsBackupTab />)
    expect(await screen.findByText(/backupTab\.infoRestartFinishesRestore/)).toBeInTheDocument()
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('shows a staged restore and cancels it', async () => {
    pending = { source_backup: FULL, staged_at: '2026-10-02T12:00:00+00:00' }
    mockedApi.delete.mockImplementation(() => {
      pending = null
      return Promise.resolve({ data: { success: true } })
    })
    render(<SettingsBackupTab />)

    const notice = await screen.findByRole('status')
    expect(within(notice).getByText('backupTab.restorePendingTitle')).toBeInTheDocument()
    expect(within(notice).getByText(FULL)).toBeInTheDocument()
    fireEvent.click(within(notice).getByRole('button', { name: 'backupTab.cancelRestore' }))

    await waitFor(() => expect(mockedApi.delete).toHaveBeenCalledWith('/backup/restore/pending'))
    expect(await screen.findByText('backupTab.cancelRestoreSuccess')).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument())
  })

  it('offers Cancel for a staged restore whose details are unreadable', async () => {
    pending = { source_backup: null, staged_at: null }
    render(<SettingsBackupTab />)

    const notice = await screen.findByRole('status')
    expect(within(notice).getByText('backupTab.restorePendingUnreadable')).toBeInTheDocument()
    expect(within(notice).getByRole('button', { name: 'backupTab.cancelRestore' })).toBeInTheDocument()
  })

  it('shows the preflight 503 detail when a restore is refused', async () => {
    const refusal =
      'Backups are refused while these secret settings are stored unencrypted: ntfy_token. ' +
      'Set MYGARAGE_SETTINGS_KEY to a valid key, or make the data directory writable so a key ' +
      'can be generated, then try again.'
    mockedApi.post.mockRejectedValue({
      isAxiosError: true,
      message: 'Request failed with status code 503',
      response: { status: 503, data: { detail: refusal } },
    })
    render(<SettingsBackupTab />)

    fireEvent.click(await screen.findByTitle('backup.restore'))

    expect(await screen.findByText(refusal)).toBeInTheDocument()
  })

  it('reloads after a refused restore, which can have dropped an earlier staging', async () => {
    pending = { source_backup: FULL, staged_at: '2026-10-02T12:00:00+00:00' }
    mockedApi.post.mockImplementation(() => {
      pending = null
      return Promise.reject(new Error('400'))
    })
    render(<SettingsBackupTab />)
    expect(await screen.findByRole('status')).toBeInTheDocument()

    fireEvent.click(screen.getByTitle('backup.restoreOverwrite'))

    await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument())
  })
})
