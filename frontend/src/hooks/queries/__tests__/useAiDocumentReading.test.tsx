import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'
import { useAiDocumentReading } from '../useAiDocumentReading'
import api from '../../../services/api'

vi.mock('../../../services/api', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))

beforeEach(() => {
  vi.clearAllMocks()
})

function Wrap({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return React.createElement(QueryClientProvider, { client: qc }, children)
}

function publicSettings(value: string | null | undefined) {
  const settings = value === undefined ? [] : [{ key: 'llm_document_reading_enabled', value }]
  return { data: { settings: [{ key: 'auth_mode', value: 'local' }, ...settings] } }
}

describe('useAiDocumentReading', () => {
  it('reads the flag from the public whitelist, not the admin list', async () => {
    vi.mocked(api.get).mockResolvedValueOnce(publicSettings('true'))

    const { result } = renderHook(() => useAiDocumentReading(), { wrapper: Wrap })
    await waitFor(() => expect(result.current.isLoading).toBe(false))

    expect(api.get).toHaveBeenCalledWith('/settings/public')
    expect(result.current.enabled).toBe(true)
  })

  it.each([['false'], [''], [null], [undefined]])('is off when the value is %s', async (value) => {
    vi.mocked(api.get).mockResolvedValueOnce(publicSettings(value))

    const { result } = renderHook(() => useAiDocumentReading(), { wrapper: Wrap })
    await waitFor(() => expect(result.current.isLoading).toBe(false))

    expect(result.current.enabled).toBe(false)
  })

  it('is off while loading and after a failed fetch', async () => {
    vi.mocked(api.get).mockRejectedValueOnce(new Error('offline'))

    const { result } = renderHook(() => useAiDocumentReading(), { wrapper: Wrap })
    expect(result.current.enabled).toBe(false)
    await waitFor(() => expect(result.current.isLoading).toBe(false))

    expect(result.current.enabled).toBe(false)
  })
})
