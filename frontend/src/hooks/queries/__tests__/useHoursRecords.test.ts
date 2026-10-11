import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'
import {
  useHoursRecords,
  useCreateHoursRecord,
  useUpdateHoursRecord,
  useDeleteHoursRecord,
  useNearestHours,
} from '../useHoursRecords'
import api from '../../../services/api'

vi.mock('../../../services/api', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
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

describe('useHoursRecords', () => {
  it('calls GET /vehicles/:vin/hours and is keyed by vin', async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      data: { records: [], total: 0, latest_engine_hours: null },
    } as { data: unknown })

    const { Wrap } = wrapper()
    const { result } = renderHook(() => useHoursRecords('1HGCM82633A004352'), { wrapper: Wrap })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))

    expect(api.get).toHaveBeenCalledWith('/vehicles/1HGCM82633A004352/hours')
    expect(result.current.data?.total).toBe(0)
  })

  it('is disabled until a vin is provided', () => {
    const { Wrap } = wrapper()
    const { result } = renderHook(() => useHoursRecords(''), { wrapper: Wrap })

    expect(result.current.fetchStatus).toBe('idle')
    expect(api.get).not.toHaveBeenCalled()
  })
})

describe('useCreateHoursRecord', () => {
  it('POSTs the payload and invalidates the hours-records list', async () => {
    vi.mocked(api.post).mockResolvedValueOnce({
      data: { id: 1, vin: '1HGCM82633A004352', date: '2026-07-30', engine_hours: '812.4' },
    } as { data: unknown })

    const { Wrap, qc } = wrapper()
    const invalidateSpy = vi.spyOn(qc, 'invalidateQueries')
    const { result } = renderHook(() => useCreateHoursRecord('1HGCM82633A004352'), { wrapper: Wrap })

    await result.current.mutateAsync({
      vin: '1HGCM82633A004352',
      date: '2026-07-30',
      engine_hours: 812.4,
    })

    expect(api.post).toHaveBeenCalledWith('/vehicles/1HGCM82633A004352/hours', {
      vin: '1HGCM82633A004352',
      date: '2026-07-30',
      engine_hours: 812.4,
    })
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['hoursRecords', '1HGCM82633A004352'] })
  })
})

describe('useUpdateHoursRecord', () => {
  it('PUTs /vehicles/:vin/hours/:id with the id stripped from the body', async () => {
    vi.mocked(api.put).mockResolvedValueOnce({ data: { id: 5 } } as { data: unknown })

    const { Wrap, qc } = wrapper()
    const invalidateSpy = vi.spyOn(qc, 'invalidateQueries')
    const { result } = renderHook(() => useUpdateHoursRecord('1HGCM82633A004352'), { wrapper: Wrap })

    await result.current.mutateAsync({ id: 5, engine_hours: 900.1 })

    expect(api.put).toHaveBeenCalledWith('/vehicles/1HGCM82633A004352/hours/5', {
      engine_hours: 900.1,
    })
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['hoursRecords', '1HGCM82633A004352'] })
  })
})

describe('useDeleteHoursRecord', () => {
  it('DELETEs /vehicles/:vin/hours/:id and invalidates the list', async () => {
    vi.mocked(api.delete).mockResolvedValueOnce({ data: null } as { data: unknown })

    const { Wrap, qc } = wrapper()
    const invalidateSpy = vi.spyOn(qc, 'invalidateQueries')
    const { result } = renderHook(() => useDeleteHoursRecord('1HGCM82633A004352'), { wrapper: Wrap })

    await result.current.mutateAsync(9)

    expect(api.delete).toHaveBeenCalledWith('/vehicles/1HGCM82633A004352/hours/9')
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['hoursRecords', '1HGCM82633A004352'] })
  })
})

describe('useNearestHours', () => {
  it('asks for the reading nearest the date', async () => {
    const reading = { date: '2026-04-01', engine_hours: '100.0', source: 'manual', days_away: -9 }
    vi.mocked(api.get).mockResolvedValueOnce({ data: reading } as { data: unknown })
    const { Wrap } = wrapper()
    const { result } = renderHook(() => useNearestHours('1HGCM82633A004352', '2026-04-10'), { wrapper: Wrap })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(api.get).toHaveBeenCalledWith('/vehicles/1HGCM82633A004352/hours/nearest', {
      params: { date: '2026-04-10' },
    })
    expect(result.current.data).toEqual(reading)
  })

  it('reads a 404 as no readings yet', async () => {
    vi.mocked(api.get).mockRejectedValueOnce({ response: { status: 404 } })
    const { Wrap } = wrapper()
    const { result } = renderHook(() => useNearestHours('1HGCM82633A004352', '2026-04-10'), { wrapper: Wrap })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toBeNull()
  })

  it('waits for a whole date', () => {
    const { Wrap } = wrapper()
    const { result } = renderHook(() => useNearestHours('1HGCM82633A004352', '2026-04'), { wrapper: Wrap })
    expect(result.current.fetchStatus).toBe('idle')
    expect(api.get).not.toHaveBeenCalled()
  })
})
