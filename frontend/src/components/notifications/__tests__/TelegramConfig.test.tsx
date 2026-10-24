/**
 * Fuel commands live with the bot they use. The server answers them only while
 * Telegram is on, so the switch follows the Telegram switch here. The status
 * line comes from the poller (admin-only); loading and saving the switch is
 * covered by SettingsNotificationsTab.test.tsx.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

import { render, screen, waitFor } from '../../../__tests__/test-utils'

const api = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('@/services/api', () => ({ default: api }))

import { TelegramConfig } from '../TelegramConfig'

const FUEL = { name: 'telegram.fuel.enable' }

function renderConfig(settings: Record<string, string>): void {
  render(
    <TelegramConfig
      settings={settings}
      onSettingChange={vi.fn()}
      onTextChange={vi.fn()}
      onTest={vi.fn()}
      testing={false}
      saving={false}
    />,
  )
}

function status(body: Record<string, unknown>): void {
  api.get.mockResolvedValue({
    data: { since: '2026-09-23T00:00:00Z', error_code: null, description: null, ...body },
  })
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('TelegramConfig fuel commands', () => {
  it('holds the switch while Telegram itself is off', () => {
    status({ state: 'off' })
    renderConfig({ telegram_enabled: 'false', telegram_inbound_enabled: 'false' })

    expect(screen.getByRole('checkbox', FUEL)).toBeDisabled()
  })

  it('asks for no webhook: there is nothing to register', () => {
    status({ state: 'off' })
    renderConfig({ telegram_enabled: 'true' })

    expect(screen.queryByText(/setWebhook/)).not.toBeInTheDocument()
  })

  it('says when it is listening', async () => {
    status({ state: 'listening' })
    renderConfig({ telegram_enabled: 'true', telegram_inbound_enabled: 'true' })

    expect(await screen.findByText('telegram.fuel.status.listening')).toBeInTheDocument()
    expect(api.get).toHaveBeenCalledWith('/notifications/telegram/fuel-commands')
  })

  it.each([
    ['starting', 'telegram.fuel.status.starting'],
    ['off', 'telegram.fuel.status.off'],
  ])('says when it is %s', async (state, key) => {
    status({ state })
    renderConfig({ telegram_enabled: 'true', telegram_inbound_enabled: 'true' })

    expect(await screen.findByText(key)).toBeInTheDocument()
  })

  it.each([
    ['bot_token_rejected', 'telegram.fuel.status.botTokenRejected'],
    ['conflict', 'telegram.fuel.status.conflict'],
    ['rate_limited', 'telegram.fuel.status.rateLimited'],
    ['unreachable', 'telegram.fuel.status.unreachable'],
    ['database_error', 'telegram.fuel.status.databaseError'],
    ['unexpected', 'telegram.fuel.status.unexpected'],
  ])('names the %s error in words', async (code, key) => {
    status({ state: 'error', error_code: code })
    renderConfig({ telegram_enabled: 'true', telegram_inbound_enabled: 'true' })

    expect(await screen.findByText(key)).toBeInTheDocument()
  })

  it("shows Telegram's own reason beside the error", async () => {
    status({
      state: 'error',
      error_code: 'conflict',
      description: 'Conflict: terminated by other getUpdates request',
    })
    renderConfig({ telegram_enabled: 'true', telegram_inbound_enabled: 'true' })

    expect(
      await screen.findByText('Conflict: terminated by other getUpdates request'),
    ).toBeInTheDocument()
  })

  it('shows no reason while listening', async () => {
    status({ state: 'listening', description: 'stale' })
    renderConfig({ telegram_enabled: 'true', telegram_inbound_enabled: 'true' })

    expect(await screen.findByText('telegram.fuel.status.listening')).toBeInTheDocument()
    expect(screen.queryByText('stale')).not.toBeInTheDocument()
  })

  it('shows no status to someone the endpoint refuses, and does not ask again', async () => {
    api.get.mockRejectedValue({ response: { status: 403 } })
    renderConfig({ telegram_enabled: 'true', telegram_inbound_enabled: 'true' })

    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(1))
    // A retry would come after TanStack's first retry delay (1 s).
    await new Promise((resolve) => setTimeout(resolve, 1200))
    expect(api.get).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })
})

describe('TelegramConfig — a switch stored as another on word', () => {
  // Rows written before the writers normalised to "true"/"false" can hold
  // "1" or "yes"; the backend reads both as on, so the toggles must too.
  it('shows telegram_enabled "1" and telegram_inbound_enabled "yes" as on', async () => {
    status({ state: 'off' })
    renderConfig({ telegram_enabled: '1', telegram_inbound_enabled: 'yes' })

    expect(screen.getByRole('checkbox', { name: 'telegram.enable' })).toBeChecked()
    expect(screen.getByRole('checkbox', FUEL)).toBeChecked()
    expect(screen.getByRole('checkbox', FUEL)).toBeEnabled()
    await waitFor(() => expect(api.get).toHaveBeenCalled())
  })
})
