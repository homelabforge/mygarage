/**
 * System tab, household-timezone behavior (plan 4.4):
 * - the select shows the real configuration even when the zone is not in the
 *   fixed list (R1-F1);
 * - a save whose batch included `timezone` waits for the page's post-save
 *   refresh (which re-reads public settings) before it reports done, so the
 *   next form opened in this tab seeds the new zone's date.
 */

import { useEffect } from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { SettingsProvider, useSettings } from '@/contexts/SettingsContext'

vi.mock('@/services/api', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn() },
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

const refreshPublicSettingsMock = vi.hoisted(() => vi.fn())
const onSaved = vi.hoisted(() => vi.fn())
vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({
    isAuthenticated: true,
    isAdmin: true,
    user: { unit_preference: 'imperial', language: 'en', currency_code: 'USD' },
    refreshUser: vi.fn(),
    refreshPublicSettings: refreshPublicSettingsMock,
  }),
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), loading: vi.fn(() => 'id') },
}))

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
      <SettingsProvider onSaved={onSaved}>
        <ActiveSystemTab />
      </SettingsProvider>
    </QueryClientProvider>,
  )
}

function mockSettings(timezone: string): void {
  mockedApi.get.mockImplementation((url: string) => {
    if (url === '/settings') {
      return Promise.resolve({
        data: {
          settings: [
            { key: 'timezone', value: timezone },
            { key: 'auth_mode', value: 'local' },
          ],
        },
      })
    }
    return Promise.resolve({ data: {} })
  })
  mockedApi.post.mockResolvedValue({ data: { settings: [] } })
}

beforeEach(() => {
  vi.clearAllMocks()
  refreshPublicSettingsMock.mockResolvedValue(undefined)
  onSaved.mockResolvedValue(undefined)
})

describe('SettingsSystemTab household timezone', () => {
  it('shows an effective zone that is NOT in the fixed list (fails if the select silently falls back)', async () => {
    mockSettings('Pacific/Kiritimati')
    renderTab()
    expect(await screen.findByDisplayValue('Pacific/Kiritimati')).toBeInTheDocument()
  })

  it('a save whose batch included timezone waits for the post-save refresh before it reports done', async () => {
    let finishRefresh: () => void = () => {}
    onSaved.mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          finishRefresh = resolve
        }),
    )
    mockSettings('UTC')
    renderTab()
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
    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1))
    expect(toast.success).not.toHaveBeenCalled()

    finishRefresh()
    await waitFor(() => expect(toast.success).toHaveBeenCalledTimes(1))
    // One refresh per save, the page's; the tab no longer asks on its own.
    expect(refreshPublicSettingsMock).not.toHaveBeenCalled()
  })
})
