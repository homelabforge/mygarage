/**
 * Which Settings tabs a person gets.
 *
 * Files, Notifications and Backup hold instance settings only, all admin-only
 * on the server, so a non-admin used to open tabs that failed to load or
 * silently failed to save. They now see System (their mobile, fuel-default and
 * archive cards) and Integrations (their widget keys). With auth off there is
 * one user and no admin, so every tab shows, as before.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderWithQueryClient } from '@/__tests__/queryClient'
import { screen } from '@testing-library/react'

const h = vi.hoisted(() => ({ isAdmin: true, authMode: 'local' }))

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({ isAdmin: h.isAdmin, authMode: h.authMode, refreshPublicSettings: vi.fn() }),
}))
vi.mock('../../components/tabs/SettingsSystemTab', () => ({ default: () => null }))
vi.mock('../../components/tabs/SettingsFilesTab', () => ({ default: () => null }))
vi.mock('../../components/tabs/SettingsIntegrationsTab', () => ({ default: () => null }))
vi.mock('../../components/tabs/SettingsNotificationsTab', () => ({ default: () => null }))
vi.mock('../../components/tabs/SettingsBackupTab', () => ({ default: () => null }))

import Settings from '../Settings'

const tabNames = (): string[] => screen.getAllByRole('tab').map((tab) => tab.textContent ?? '')

beforeEach(() => {
  h.isAdmin = true
  h.authMode = 'local'
})

describe('Settings tabs', () => {
  it('gives an admin every tab', () => {
    renderWithQueryClient(<Settings />)
    expect(tabNames()).toEqual([
      'tabs.system',
      'tabs.fileManagement',
      'tabs.integrations',
      'tabs.notifications',
      'tabs.backupRestore',
    ])
  })

  it('gives a non-admin only the tabs with something of theirs', () => {
    h.isAdmin = false
    renderWithQueryClient(<Settings />)
    expect(tabNames()).toEqual(['tabs.system', 'tabs.integrations'])
  })

  it('gives every tab to the single user when auth is off', () => {
    h.isAdmin = false
    h.authMode = 'none'
    renderWithQueryClient(<Settings />)
    expect(tabNames()).toHaveLength(5)
  })
})
