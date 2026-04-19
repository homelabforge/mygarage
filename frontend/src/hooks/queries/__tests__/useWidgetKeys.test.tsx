import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'
import {
  isAuthDisabledError,
  useWidgetKeys,
  useCreateWidgetKey,
  useRevokeWidgetKey,
} from '../useWidgetKeys'
import api from '../../../services/api'

vi.mock('../../../services/api', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    delete: vi.fn(),
  },
}))

function wrapper() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  return function Wrap({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  }
}

describe('isAuthDisabledError', () => {
  it('returns true for the structured 400 body', () => {
    expect(
      isAuthDisabledError({
        response: { status: 400, data: { detail: { detail: 'widget_keys_require_auth' } } },
      }),
    ).toBe(true)
  })

  it('returns false for generic 400s', () => {
    expect(
      isAuthDisabledError({ response: { status: 400, data: { detail: { detail: 'other' } } } }),
    ).toBe(false)
  })

  it('returns false for non-400 errors', () => {
    expect(isAuthDisabledError({ response: { status: 500 } })).toBe(false)
    expect(isAuthDisabledError(null)).toBe(false)
    expect(isAuthDisabledError(undefined)).toBe(false)
  })
})

describe('useWidgetKeys', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('calls GET /auth/me/widget-keys and returns data', async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      data: { keys: [{ id: 1, name: 'test' }] },
    } as { data: unknown })

    const { result } = renderHook(() => useWidgetKeys(), { wrapper: wrapper() })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))

    expect(api.get).toHaveBeenCalledWith('/auth/me/widget-keys')
    expect(result.current.data?.keys).toHaveLength(1)
  })

  it('does not retry on the auth-disabled 400', async () => {
    const err = {
      response: {
        status: 400,
        data: { detail: { detail: 'widget_keys_require_auth' } },
      },
    }
    vi.mocked(api.get).mockRejectedValue(err)
    const { result } = renderHook(() => useWidgetKeys(), { wrapper: wrapper() })
    await waitFor(() => expect(result.current.isError).toBe(true))
    // Exactly one call — retry should have been suppressed.
    expect(api.get).toHaveBeenCalledTimes(1)
  })
})

describe('useCreateWidgetKey', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('POSTs the payload and returns the created key', async () => {
    vi.mocked(api.post).mockResolvedValueOnce({
      data: {
        id: 42,
        name: 'homepage',
        secret: 'mgwk_abc',
        key_prefix: 'mgwk_abc',
        scope: 'all_vehicles',
        allowed_vins: null,
        created_at: '2026-04-19T00:00:00Z',
        last_used_at: null,
        revoked_at: null,
      },
    } as { data: unknown })

    const { result } = renderHook(() => useCreateWidgetKey(), { wrapper: wrapper() })
    const created = await result.current.mutateAsync({
      name: 'homepage',
      scope: 'all_vehicles',
      allowed_vins: null,
    })
    expect(api.post).toHaveBeenCalledWith(
      '/auth/me/widget-keys',
      { name: 'homepage', scope: 'all_vehicles', allowed_vins: null },
    )
    expect(created.secret).toBe('mgwk_abc')
  })
})

describe('useRevokeWidgetKey', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('DELETEs the id and resolves', async () => {
    vi.mocked(api.delete).mockResolvedValueOnce({ data: null } as { data: unknown })
    const { result } = renderHook(() => useRevokeWidgetKey(), { wrapper: wrapper() })
    const returned = await result.current.mutateAsync(7)
    expect(api.delete).toHaveBeenCalledWith('/auth/me/widget-keys/7')
    expect(returned).toBe(7)
  })
})
