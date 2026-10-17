import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/services/api'
import type {
  BrakeAxleName,
  BrakeAxleUpdate,
  BrakeJobCreate,
  BrakeJobUpdate,
  BrakeMeasurementBatchCreate,
  BrakeMeasurementUpdate,
  BrakeOverview,
} from '@/types/brake'

/** A vehicle's brakes: both axles and the four corners. */
export function useBrakes(vin: string) {
  return useQuery({
    queryKey: ['brakes', vin],
    queryFn: async () => {
      const { data } = await api.get<BrakeOverview>(`/vehicles/${vin}/brakes`)
      return data
    },
    enabled: !!vin,
  })
}

/**
 * Everything a brake write moves: the brakes, the axle reminders it raises
 * or completes, and the hero's reminder counts. Brake writes never touch the
 * odometer or hour meter history, so the reading views stay as they are.
 */
function invalidateBrakeViews(queryClient: ReturnType<typeof useQueryClient>, vin: string): void {
  for (const key of ['brakes', 'reminders', 'vehicleDetailStats']) {
    void queryClient.invalidateQueries({ queryKey: [key, vin] })
  }
}

/** Save one axle's setup. */
export function useUpdateBrakeAxle(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ axle, ...payload }: BrakeAxleUpdate & { axle: BrakeAxleName }) => {
      const { data } = await api.put<BrakeOverview>(`/vehicles/${vin}/brakes/axles/${axle}`, payload)
      return data
    },
    onSuccess: () => invalidateBrakeViews(queryClient, vin),
  })
}

/** Record one to four corners measured on one day. */
export function useLogBrakeMeasurements(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (payload: BrakeMeasurementBatchCreate) => {
      const { data } = await api.post<BrakeOverview>(`/vehicles/${vin}/brakes/measurements`, payload)
      return data
    },
    onSuccess: () => invalidateBrakeViews(queryClient, vin),
  })
}

/** Correct one measurement. Omitted keeps a field, null clears it. */
export function useUpdateBrakeMeasurement(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, ...payload }: BrakeMeasurementUpdate & { id: number }) => {
      const { data } = await api.put<BrakeOverview>(`/vehicles/${vin}/brakes/measurements/${id}`, payload)
      return data
    },
    onSuccess: () => invalidateBrakeViews(queryClient, vin),
  })
}

export function useDeleteBrakeMeasurement(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (id: number) => {
      await api.delete(`/vehicles/${vin}/brakes/measurements/${id}`)
    },
    onSuccess: () => invalidateBrakeViews(queryClient, vin),
  })
}

/** Record a brake job on one to four corners. */
export function useCreateBrakeJob(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (payload: BrakeJobCreate) => {
      const { data } = await api.post<BrakeOverview>(`/vehicles/${vin}/brakes/jobs`, payload)
      return data
    },
    onSuccess: () => invalidateBrakeViews(queryClient, vin),
  })
}

/** Correct one corner's brake job. The new-pads figure it wrote moves with it. */
export function useUpdateBrakeJob(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, ...payload }: BrakeJobUpdate & { id: number }) => {
      const { data } = await api.put<BrakeOverview>(`/vehicles/${vin}/brakes/jobs/${id}`, payload)
      return data
    },
    onSuccess: () => invalidateBrakeViews(queryClient, vin),
  })
}

export function useDeleteBrakeJob(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (id: number) => {
      await api.delete(`/vehicles/${vin}/brakes/jobs/${id}`)
    },
    onSuccess: () => invalidateBrakeViews(queryClient, vin),
  })
}
