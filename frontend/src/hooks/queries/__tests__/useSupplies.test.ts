import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'
import {
  useSupplies,
  useCreateSupply,
  useUpdateSupply,
  useDeleteSupply,
  useSupplyHistory,
  useAddPurchase,
  useDeletePurchase,
  useAddAdjustment,
  useDeleteAdjustment,
  useUploadReceipt,
  useDeleteReceipt,
  useVehicleSupplyUsages,
} from '../useSupplies'
import api from '../../../services/api'

vi.mock('../../../services/api', () => ({
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

function wrapper() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  return {
    qc,
    Wrap: function Wrap({ children }: { children: React.ReactNode }) {
      return React.createElement(QueryClientProvider, { client: qc }, children)
    },
  }
}

describe('useSupplies', () => {
  it('calls GET /supplies with no params by default', async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      data: { supplies: [], total: 0 },
    } as { data: unknown })

    const { Wrap } = wrapper()
    const { result } = renderHook(() => useSupplies(), { wrapper: Wrap })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))

    expect(api.get).toHaveBeenCalledWith('/supplies', { params: {} })
    expect(result.current.data?.total).toBe(0)
  })

  it('builds query params from includeArchived and vin', async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      data: { supplies: [], total: 0 },
    } as { data: unknown })

    const { Wrap } = wrapper()
    const { result } = renderHook(() => useSupplies(true, '1HGCM82633A004352'), {
      wrapper: Wrap,
    })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))

    expect(api.get).toHaveBeenCalledWith('/supplies', {
      params: { include_archived: true, vin: '1HGCM82633A004352' },
    })
  })
})

describe('useCreateSupply', () => {
  it('POSTs the payload and invalidates the supplies list', async () => {
    vi.mocked(api.post).mockResolvedValueOnce({
      data: { id: 1, name: 'Oil filter' },
    } as { data: unknown })

    const { Wrap, qc } = wrapper()
    const invalidateSpy = vi.spyOn(qc, 'invalidateQueries')
    const { result } = renderHook(() => useCreateSupply(), { wrapper: Wrap })

    await result.current.mutateAsync({ name: 'Oil filter', unit_type: 'count' })

    expect(api.post).toHaveBeenCalledWith('/supplies', {
      name: 'Oil filter',
      unit_type: 'count',
    })
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['supplies'] })
  })
})

describe('useUpdateSupply', () => {
  it('PATCHes /supplies/:id with the id stripped from the body', async () => {
    vi.mocked(api.patch).mockResolvedValueOnce({ data: { id: 5 } } as { data: unknown })

    const { Wrap } = wrapper()
    const { result } = renderHook(() => useUpdateSupply(), { wrapper: Wrap })

    await result.current.mutateAsync({ id: 5, name: 'Renamed' })

    expect(api.patch).toHaveBeenCalledWith('/supplies/5', { name: 'Renamed' })
  })
})

describe('useDeleteSupply', () => {
  it('DELETEs /supplies/:id', async () => {
    vi.mocked(api.delete).mockResolvedValueOnce({ data: null } as { data: unknown })

    const { Wrap } = wrapper()
    const { result } = renderHook(() => useDeleteSupply(), { wrapper: Wrap })

    await result.current.mutateAsync(9)

    expect(api.delete).toHaveBeenCalledWith('/supplies/9')
  })
})

describe('useSupplyHistory', () => {
  it('is disabled until a supplyId is provided', () => {
    const { Wrap } = wrapper()
    const { result } = renderHook(() => useSupplyHistory(undefined), { wrapper: Wrap })

    expect(result.current.fetchStatus).toBe('idle')
    expect(api.get).not.toHaveBeenCalled()
  })

  it('calls GET /supplies/:id/history under the supply-history key', async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      data: { supply_id: 3, on_hand: '2', entries: [] },
    } as { data: unknown })

    const { Wrap } = wrapper()
    const { result } = renderHook(() => useSupplyHistory(3), { wrapper: Wrap })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))

    expect(api.get).toHaveBeenCalledWith('/supplies/3/history')
  })
})

describe('useAddPurchase', () => {
  it('POSTs a purchase and invalidates supplies + supply-history', async () => {
    vi.mocked(api.post).mockResolvedValueOnce({ data: { id: 11 } } as { data: unknown })

    const { Wrap, qc } = wrapper()
    const invalidateSpy = vi.spyOn(qc, 'invalidateQueries')
    const { result } = renderHook(() => useAddPurchase(3), { wrapper: Wrap })

    await result.current.mutateAsync({ date: '2026-07-17', quantity: 1 })

    expect(api.post).toHaveBeenCalledWith('/supplies/3/purchases', {
      date: '2026-07-17',
      quantity: 1,
    })
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['supplies'] })
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['supply-history', 3] })
  })
})

describe('useDeletePurchase', () => {
  it('DELETEs /supplies/:id/purchases/:purchaseId', async () => {
    vi.mocked(api.delete).mockResolvedValueOnce({ data: null } as { data: unknown })

    const { Wrap } = wrapper()
    const { result } = renderHook(() => useDeletePurchase(3), { wrapper: Wrap })

    await result.current.mutateAsync(11)

    expect(api.delete).toHaveBeenCalledWith('/supplies/3/purchases/11')
  })
})

describe('useAddAdjustment', () => {
  it('POSTs an adjustment and invalidates supplies + supply-history', async () => {
    vi.mocked(api.post).mockResolvedValueOnce({ data: { id: 21 } } as { data: unknown })

    const { Wrap, qc } = wrapper()
    const invalidateSpy = vi.spyOn(qc, 'invalidateQueries')
    const { result } = renderHook(() => useAddAdjustment(3), { wrapper: Wrap })

    await result.current.mutateAsync({ quantity: 1 })

    expect(api.post).toHaveBeenCalledWith('/supplies/3/adjustments', { quantity: 1 })
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['supply-history', 3] })
  })
})

describe('useDeleteAdjustment', () => {
  it('DELETEs /supplies/:id/adjustments/:usageId', async () => {
    vi.mocked(api.delete).mockResolvedValueOnce({ data: null } as { data: unknown })

    const { Wrap } = wrapper()
    const { result } = renderHook(() => useDeleteAdjustment(3), { wrapper: Wrap })

    await result.current.mutateAsync(21)

    expect(api.delete).toHaveBeenCalledWith('/supplies/3/adjustments/21')
  })
})

describe('useUploadReceipt', () => {
  it('POSTs FormData with the multipart header and invalidates the ledger', async () => {
    vi.mocked(api.post).mockResolvedValueOnce({ data: { id: 1 } } as { data: unknown })

    const { Wrap, qc } = wrapper()
    const invalidateSpy = vi.spyOn(qc, 'invalidateQueries')
    const { result } = renderHook(() => useUploadReceipt(3), { wrapper: Wrap })
    const formData = new FormData()

    await result.current.mutateAsync({ purchaseId: 11, formData })

    expect(api.post).toHaveBeenCalledWith(
      '/supplies/3/purchases/11/receipt',
      formData,
      { headers: { 'Content-Type': 'multipart/form-data' } }
    )
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['supply-history', 3] })
  })
})

describe('useDeleteReceipt', () => {
  it('DELETEs /supplies/:id/purchases/:purchaseId/receipt', async () => {
    vi.mocked(api.delete).mockResolvedValueOnce({ data: null } as { data: unknown })

    const { Wrap } = wrapper()
    const { result } = renderHook(() => useDeleteReceipt(3), { wrapper: Wrap })

    await result.current.mutateAsync(11)

    expect(api.delete).toHaveBeenCalledWith('/supplies/3/purchases/11/receipt')
  })
})

describe('useVehicleSupplyUsages', () => {
  it('is disabled until a vin is provided', () => {
    const { Wrap } = wrapper()
    const { result } = renderHook(() => useVehicleSupplyUsages(undefined), { wrapper: Wrap })

    expect(result.current.fetchStatus).toBe('idle')
    expect(api.get).not.toHaveBeenCalled()
  })

  it('calls GET /vehicles/:vin/supply-usages', async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      data: { total: 0, usages: [] },
    } as { data: unknown })

    const { Wrap } = wrapper()
    const { result } = renderHook(() => useVehicleSupplyUsages('1HGCM82633A004352'), {
      wrapper: Wrap,
    })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))

    expect(api.get).toHaveBeenCalledWith('/vehicles/1HGCM82633A004352/supply-usages')
  })
})
