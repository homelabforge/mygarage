/**
 * Tire mutations invalidate the odometer caches.
 *
 * Every tire operation publishes, moves or deletes vehicle odometer records,
 * and until this file none of them invalidated `['odometerRecords', vin]`, so
 * the Odometer tab and the nearest-reading suggestion could show a value the
 * server no longer held for the 30-second stale time. Component tests mock
 * the hooks away, so this is the only place the invalidation is observable.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'

import api from '@/services/api'
import {
  useCreateMountPeriod,
  useDeleteTire,
  useDeleteTireReading,
  useMountTire,
  useTires,
  useUpdateMountPeriod,
  useUpdateTireReading,
} from '../useTires'

const VIN = '1HGCM82633A004352'
const NEAREST_KEY = ['odometerRecords', VIN, 'nearest', '2026-04-10']
const LIST_KEY = ['odometerRecords', VIN]

function harness() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  queryClient.setQueryData(LIST_KEY, { records: [], total: 0 })
  queryClient.setQueryData(NEAREST_KEY, {
    date: '2026-04-01',
    odometer_km: '100000',
    source: 'manual',
    days_away: -9,
  })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
  return { queryClient, wrapper }
}

const invalidated = (qc: QueryClient, key: unknown[]) =>
  qc.getQueryState(key)?.isInvalidated === true

describe('tire mutations invalidate the odometer caches', () => {
  beforeEach(() => {
    vi.mocked(api.post).mockResolvedValue({ data: {} })
    vi.mocked(api.put).mockResolvedValue({ data: {} })
    vi.mocked(api.delete).mockResolvedValue({ data: {} })
  })

  it('a mount invalidates the list and the nearest suggestion', async () => {
    const { queryClient, wrapper } = harness()
    const { result } = renderHook(() => useMountTire(VIN), { wrapper })
    await act(async () => {
      await result.current.mutateAsync({ tireId: 1, position: 'FL' })
    })
    expect(invalidated(queryClient, LIST_KEY)).toBe(true)
    expect(invalidated(queryClient, NEAREST_KEY)).toBe(true)
  })

  it('a period edit invalidates them', async () => {
    const { queryClient, wrapper } = harness()
    const { result } = renderHook(() => useUpdateMountPeriod(VIN), { wrapper })
    await act(async () => {
      await result.current.mutateAsync({ tireId: 1, periodId: 2, notes: 'x' })
    })
    expect(vi.mocked(api.put)).toHaveBeenCalledWith('/vehicles/' + VIN + '/tires/1/mount-periods/2', { notes: 'x' })
    expect(invalidated(queryClient, LIST_KEY)).toBe(true)
    expect(invalidated(queryClient, NEAREST_KEY)).toBe(true)
  })

  it('recording a past period posts to the tire and invalidates every prefix invalidateTireViews covers', async () => {
    const { queryClient, wrapper } = harness()
    const keys = {
      tires: ['tires', VIN, false],
      reminders: ['reminders', VIN],
      sets: ['tire-sets', VIN],
      odometer: LIST_KEY,
    }
    for (const key of Object.values(keys)) queryClient.setQueryData(key, {})

    const { result } = renderHook(() => useCreateMountPeriod(VIN), { wrapper })
    await act(async () => {
      await result.current.mutateAsync({
        tireId: 3,
        position: 'FR',
        mounted_on: '2025-09-15',
        dismounted_on: '2025-12-15',
        mounted_odometer_km: 1610.148672,
        dismounted_odometer_km: 19868.3172864,
        notes: null,
      })
    })
    expect(vi.mocked(api.post)).toHaveBeenCalledWith('/vehicles/' + VIN + '/tires/3/mount-periods', {
      position: 'FR',
      mounted_on: '2025-09-15',
      dismounted_on: '2025-12-15',
      mounted_odometer_km: 1610.148672,
      dismounted_odometer_km: 19868.3172864,
      notes: null,
    })
    expect(invalidated(queryClient, keys.tires)).toBe(true)
    expect(invalidated(queryClient, keys.reminders)).toBe(true)
    expect(invalidated(queryClient, keys.sets)).toBe(true)
    expect(invalidated(queryClient, keys.odometer)).toBe(true)
  })

  it('a delete invalidates them', async () => {
    const { queryClient, wrapper } = harness()
    const { result } = renderHook(() => useDeleteTire(VIN), { wrapper })
    await act(async () => {
      await result.current.mutateAsync(1)
    })
    expect(invalidated(queryClient, LIST_KEY)).toBe(true)
    expect(invalidated(queryClient, NEAREST_KEY)).toBe(true)
  })
})

describe('deleting a reading', () => {
  beforeEach(() => {
    vi.mocked(api.delete).mockResolvedValue({ data: {} })
  })

  it('invalidates every view a tire write can change, and only this vehicle\'s', async () => {
    const { queryClient, wrapper } = harness()
    const OTHER = '2T1BURHE0JC000001'
    const keys = {
      tires: ['tires', VIN, false],
      reminders: ['reminders', VIN],
      sets: ['tire-sets', VIN],
      odometer: LIST_KEY,
      otherVehicle: ['tires', OTHER, false],
    }
    for (const key of Object.values(keys)) queryClient.setQueryData(key, {})

    const { result } = renderHook(() => useDeleteTireReading(VIN), { wrapper })
    await act(async () => {
      await result.current.mutateAsync({ tireId: 4, readingId: 17 })
    })

    expect(vi.mocked(api.delete)).toHaveBeenCalledWith('/vehicles/' + VIN + '/tires/4/readings/17')
    expect(invalidated(queryClient, keys.tires)).toBe(true)
    expect(invalidated(queryClient, keys.reminders)).toBe(true)
    expect(invalidated(queryClient, keys.sets)).toBe(true)
    expect(invalidated(queryClient, keys.odometer)).toBe(true)
    expect(invalidated(queryClient, NEAREST_KEY)).toBe(true)
    expect(invalidated(queryClient, keys.otherVehicle)).toBe(false)
  })
})

describe('editing a reading', () => {
  beforeEach(() => {
    vi.mocked(api.put).mockResolvedValue({ data: {} })
  })

  it('puts the body without the ids and refreshes every view a reading moves, the list once', async () => {
    const { queryClient, wrapper } = harness()
    const keys = {
      tires: ['tires', VIN, false],
      reminders: ['reminders', VIN],
      sets: ['tire-sets', VIN],
      odometer: LIST_KEY,
      hours: ['hoursRecords', VIN],
    }
    for (const key of Object.values(keys)) queryClient.setQueryData(key, {})
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')

    const { result } = renderHook(() => useUpdateTireReading(VIN), { wrapper })
    await act(async () => {
      await result.current.mutateAsync({ tireId: 4, readingId: 17, tread_depth_mm: 7.9375, engine_hours: 155 })
    })

    expect(vi.mocked(api.put)).toHaveBeenCalledWith('/vehicles/' + VIN + '/tires/4/readings/17', {
      tread_depth_mm: 7.9375,
      engine_hours: 155,
    })
    for (const key of Object.values(keys)) expect(invalidated(queryClient, key)).toBe(true)
    expect(invalidated(queryClient, NEAREST_KEY)).toBe(true)
    const listCalls = invalidate.mock.calls.filter(
      ([filters]) => JSON.stringify(filters?.queryKey) === JSON.stringify(['tires', VIN])
    )
    expect(listCalls).toHaveLength(1)
  })
})

describe('useTires across the Show retired toggle', () => {
  const listed = (ids: number[]) => ({ tires: ids.map((id) => ({ id })), total: ids.length })

  it('keeps the list on screen while the other variant loads', async () => {
    const { wrapper } = harness()
    let finish: (value: { data: unknown }) => void = () => {}
    vi.mocked(api.get)
      .mockResolvedValueOnce({ data: listed([1]) })
      .mockImplementationOnce(() => new Promise((resolve) => (finish = resolve)))

    const { result, rerender } = renderHook(
      ({ vin, includeRetired }: { vin: string; includeRetired: boolean }) =>
        useTires(vin, includeRetired),
      { wrapper, initialProps: { vin: VIN, includeRetired: false } }
    )
    await waitFor(() => expect(result.current.isSuccess).toBe(true))

    rerender({ vin: VIN, includeRetired: true })
    // Dropping to undefined here is what flashed the whole tab to loading.
    expect(result.current.data).toEqual(listed([1]))
    expect(result.current.isPlaceholderData).toBe(true)

    await act(async () => finish({ data: listed([1, 2]) }))
    await waitFor(() => expect(result.current.data).toEqual(listed([1, 2])))
    expect(result.current.isPlaceholderData).toBe(false)
  })

  it('never shows one vehicle\'s tires while another vehicle\'s load', async () => {
    const { wrapper } = harness()
    vi.mocked(api.get)
      .mockResolvedValueOnce({ data: listed([1]) })
      .mockImplementationOnce(() => new Promise(() => {}))

    const { result, rerender } = renderHook(
      ({ vin, includeRetired }: { vin: string; includeRetired: boolean }) =>
        useTires(vin, includeRetired),
      { wrapper, initialProps: { vin: VIN, includeRetired: false } }
    )
    await waitFor(() => expect(result.current.isSuccess).toBe(true))

    rerender({ vin: '2T1BURHE0JC000001', includeRetired: false })
    expect(result.current.data).toBeUndefined()
    expect(result.current.isLoading).toBe(true)
  })
})

describe('a tire write refreshes the tire list once (#217)', () => {
  it('names the list once, since invalidateReadingViews already covers it', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: {} })
    const { queryClient, wrapper } = harness()
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')
    const { result } = renderHook(() => useMountTire(VIN), { wrapper })
    await act(async () => {
      await result.current.mutateAsync({ tireId: 1, position: 'FL' })
    })
    // Two invalidations in one tick fetch the list twice.
    const listCalls = invalidate.mock.calls.filter(
      ([filters]) => JSON.stringify(filters?.queryKey) === JSON.stringify(['tires', VIN])
    )
    expect(listCalls).toHaveLength(1)
  })
})
