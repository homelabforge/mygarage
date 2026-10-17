/**
 * Brake mutations (#202) refresh the brakes and the reminders they move, and
 * leave the odometer and hour meter alone: a brake write never publishes a reading.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'

import api from '@/services/api'
import { useCreateBrakeJob, useLogBrakeMeasurements, useUpdateBrakeAxle } from '../useBrakes'

const VIN = '1HGCM82633A004352'

function harness() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  for (const key of ['brakes', 'reminders', 'odometerRecords', 'latestMileage']) {
    queryClient.setQueryData([key, VIN], {})
  }
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
  return { queryClient, wrapper }
}

const invalidated = (qc: QueryClient, key: string): boolean =>
  qc.getQueryState([key, VIN])?.isInvalidated === true

describe('brake mutations', () => {
  beforeEach(() => {
    vi.mocked(api.post).mockResolvedValue({ data: {} })
    vi.mocked(api.put).mockResolvedValue({ data: {} })
  })

  it('logging measurements posts the batch and refreshes brakes and reminders only', async () => {
    const { queryClient, wrapper } = harness()
    const { result } = renderHook(() => useLogBrakeMeasurements(VIN), { wrapper })
    const payload = { recorded_at: '2026-10-01', corners: [{ position: 'FL' as const, inner_pad_mm: 6 }] }
    await act(async () => {
      await result.current.mutateAsync(payload)
    })
    expect(api.post).toHaveBeenCalledWith(`/vehicles/${VIN}/brakes/measurements`, payload)
    expect(invalidated(queryClient, 'brakes')).toBe(true)
    expect(invalidated(queryClient, 'reminders')).toBe(true)
    expect(invalidated(queryClient, 'odometerRecords')).toBe(false)
    expect(invalidated(queryClient, 'latestMileage')).toBe(false)
  })

  it('the axle goes in the path, not the body', async () => {
    const { wrapper } = harness()
    const { result } = renderHook(() => useUpdateBrakeAxle(VIN), { wrapper })
    await act(async () => {
      await result.current.mutateAsync({ axle: 'rear', brake_type: 'drum', min_thickness_mm: 1.5, new_thickness_mm: 5 })
    })
    expect(api.put).toHaveBeenCalledWith(`/vehicles/${VIN}/brakes/axles/rear`, {
      brake_type: 'drum',
      min_thickness_mm: 1.5,
      new_thickness_mm: 5,
    })
  })

  it('a brake job posts to the jobs endpoint', async () => {
    const { queryClient, wrapper } = harness()
    const { result } = renderHook(() => useCreateBrakeJob(VIN), { wrapper })
    await act(async () => {
      await result.current.mutateAsync({ performed_on: '2026-10-01', friction_replaced: true, corners: [{ position: 'FL' }] })
    })
    expect(api.post).toHaveBeenCalledWith(`/vehicles/${VIN}/brakes/jobs`, expect.objectContaining({ friction_replaced: true }))
    expect(invalidated(queryClient, 'brakes')).toBe(true)
  })
})
