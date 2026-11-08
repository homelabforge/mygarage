/**
 * AuthContext feeds the household-zone store from `/settings/public` and
 * keeps it current: refreshPublicSettings() on demand, and a rate-limited
 * refetch when the document becomes visible (plan 4.5.1).
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { screen, waitFor, act } from '@testing-library/react'
import { renderWithQueryClient } from '@/__tests__/queryClient'
import { AuthProvider, useAuth } from '../AuthContext'
import { getHouseholdTimeZone, setHouseholdTimeZone } from '../../constants/i18n'

vi.mock('../../services/api', () => ({
  default: { get: vi.fn(), post: vi.fn() },
  setCSRFToken: vi.fn(),
  getCSRFToken: vi.fn(),
  clearCSRFToken: vi.fn(),
  setApiAuthMode: vi.fn(),
}))

import api from '../../services/api'

const mockedApi = vi.mocked(api)

function publicPayload(zone: string) {
  return {
    data: {
      settings: [
        { key: 'auth_mode', value: 'none' },
        { key: 'effective_timezone', value: zone },
      ],
    },
  }
}

function Probe() {
  const { refreshPublicSettings, loading } = useAuth()
  return (
    <button disabled={loading} onClick={() => void refreshPublicSettings()}>
      refresh
    </button>
  )
}

let nowSpy: ReturnType<typeof vi.spyOn>

beforeEach(() => {
  vi.clearAllMocks()
  setHouseholdTimeZone(null)
  nowSpy = vi.spyOn(Date, 'now').mockReturnValue(1_000_000)
})

afterEach(() => {
  setHouseholdTimeZone(null)
  nowSpy.mockRestore()
})

const publicCalls = () =>
  mockedApi.get.mock.calls.filter(([url]) => url === '/settings/public').length

describe('AuthContext household zone', () => {
  it('boot reads effective_timezone into the store; refreshPublicSettings picks up a change', async () => {
    mockedApi.get.mockResolvedValue(publicPayload('America/Chicago'))
    renderWithQueryClient(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    )
    await waitFor(() => expect(getHouseholdTimeZone()).toBe('America/Chicago'))

    mockedApi.get.mockResolvedValue(publicPayload('Europe/Warsaw'))
    screen.getByRole('button').click()
    await waitFor(() => expect(getHouseholdTimeZone()).toBe('Europe/Warsaw'))
  })

  it('refreshPublicSettings asks the server even while the cache is fresh, and updates it', async () => {
    mockedApi.get.mockResolvedValue(publicPayload('America/Chicago'))
    const { client } = renderWithQueryClient(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    )
    await waitFor(() => expect(getHouseholdTimeZone()).toBe('America/Chicago'))
    expect(publicCalls()).toBe(1)

    // Date.now is pinned, so the boot answer is as fresh as it gets.
    mockedApi.get.mockResolvedValue(publicPayload('Europe/Warsaw'))
    screen.getByRole('button').click()
    await waitFor(() => expect(getHouseholdTimeZone()).toBe('Europe/Warsaw'))
    expect(publicCalls()).toBe(2)
    expect(client.getQueryData(['settings', 'public'])).toEqual(publicPayload('Europe/Warsaw').data.settings)
  })

  it('a failed refresh keeps the current values', async () => {
    mockedApi.get.mockResolvedValue(publicPayload('America/Chicago'))
    renderWithQueryClient(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    )
    await waitFor(() => expect(getHouseholdTimeZone()).toBe('America/Chicago'))

    mockedApi.get.mockRejectedValue(new Error('offline'))
    screen.getByRole('button').click()
    await waitFor(() => expect(publicCalls()).toBe(2))
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(getHouseholdTimeZone()).toBe('America/Chicago')
  })

  it('visibilitychange refetches once outside the 60s window and not inside it', async () => {
    mockedApi.get.mockResolvedValue(publicPayload('America/Chicago'))
    renderWithQueryClient(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    )
    await waitFor(() => expect(publicCalls()).toBe(1))

    Object.defineProperty(document, 'visibilityState', {
      configurable: true,
      get: () => 'visible',
    })

    // Within 60s of the boot fetch: rate-limited, no refetch.
    nowSpy.mockReturnValue(1_000_000 + 30_000)
    act(() => {
      document.dispatchEvent(new Event('visibilitychange'))
    })
    expect(publicCalls()).toBe(1)

    // Past the window: exactly one refetch...
    nowSpy.mockReturnValue(1_000_000 + 61_000)
    act(() => {
      document.dispatchEvent(new Event('visibilitychange'))
    })
    await waitFor(() => expect(publicCalls()).toBe(2))

    // ...and a second event right after is limited again.
    nowSpy.mockReturnValue(1_000_000 + 62_000)
    act(() => {
      document.dispatchEvent(new Event('visibilitychange'))
    })
    expect(publicCalls()).toBe(2)
  })
})
