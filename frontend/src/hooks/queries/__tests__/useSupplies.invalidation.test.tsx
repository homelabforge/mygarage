import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { useUpdateSupply } from '../useSupplies'
import api from '@/services/api'

vi.mock('@/services/api', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}))

beforeEach(() => {
  vi.clearAllMocks()
})

describe('useUpdateSupply invalidation', () => {
  it('a supply edit also refreshes the usage tab and the service visits', async () => {
    vi.mocked(api.patch).mockResolvedValueOnce({ data: { id: 7, volume_unit: 'mL' } } as {
      data: unknown
    })
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    // Per-vin entries, so the prefix match is proven on real keys and not just the call shape.
    qc.setQueryData(['vehicle-supply-usages', 'VIN1'], { usages: [], total: 0 })
    qc.setQueryData(['serviceVisits', 'VIN1'], [])
    const invalidateSpy = vi.spyOn(qc, 'invalidateQueries')

    const { result } = renderHook(() => useUpdateSupply(), {
      wrapper: ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={qc}>{children}</QueryClientProvider>
      ),
    })
    await result.current.mutateAsync({ id: 7, volume_unit: 'mL' })

    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['supplies'] })
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['vehicle-supply-usages'] })
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['serviceVisits'] })
    expect(qc.getQueryState(['vehicle-supply-usages', 'VIN1'])?.isInvalidated).toBe(true)
    expect(qc.getQueryState(['serviceVisits', 'VIN1'])?.isInvalidated).toBe(true)
  })
})
