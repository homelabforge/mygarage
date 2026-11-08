/**
 * The secrets banner names what can't be read the way the Settings tabs do, so
 * an admin knows which field to re-enter. A key the client has no label for
 * (a newer backend) still shows, as its raw name.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, within } from '@testing-library/react'
import { renderWithQueryClient } from '@/__tests__/queryClient'
import SecretsStatusBanner from '../SecretsStatusBanner'

vi.mock('react-i18next', async () => (await import('@/__tests__/i18nEn')).reactI18nextEn())

const h = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('@/services/api', () => ({ default: { get: h.get } }))

function answer(unreadable: string[]): void {
  h.get.mockResolvedValue({ data: { keyring: 'ok', unreadable_keys: unreadable } })
}

beforeEach(() => {
  h.get.mockReset()
})

describe('SecretsStatusBanner labels', () => {
  it('names each unreadable secret by its label, not its setting key', async () => {
    answer(['gotify_token', 'llm_api_key', 'oidc_client_secret'])
    renderWithQueryClient(<SecretsStatusBanner />)

    const banner = await screen.findByRole('alert')
    const items = within(banner).getAllByRole('listitem').map((li) => li.textContent)
    expect(items).toEqual(['Gotify app token', 'AI provider API key', 'SSO client secret'])
    expect(banner).not.toHaveTextContent('gotify_token')
    expect(banner).not.toHaveTextContent('llm_api_key')
  })

  it('falls back to the raw key for a secret it has no label for', async () => {
    answer(['some_future_secret', 'ntfy_token'])
    renderWithQueryClient(<SecretsStatusBanner />)

    const banner = await screen.findByRole('alert')
    const items = within(banner).getAllByRole('listitem').map((li) => li.textContent)
    expect(items).toEqual(['some_future_secret', 'ntfy access token'])
  })
})
