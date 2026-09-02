import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/services/api'
import type {
  Tire,
  TireCreate,
  TireCreateAndMountRequest,
  TireDismountRequest,
  TireListResponse,
  TireMountRequest,
  TireReadingCreate,
  TireRotationRequest,
  TireUpdate,
} from '@/types/tire'

export function useTires(vin: string) {
  return useQuery({
    queryKey: ['tires', vin],
    queryFn: async () => {
      const { data } = await api.get<TireListResponse>(`/vehicles/${vin}/tires`)
      return data
    },
    enabled: !!vin,
  })
}

/**
 * Invalidations every tire mutation needs.
 *
 * `reminders` because the low-tread sync raises and clears one, and `odometer`
 * because a mount or rotation can carry an odometer reading. Written once
 * rather than repeated in seven mutations, where one of them would eventually
 * be missing an entry and the symptom would be a stale card nobody could
 * reproduce.
 */
function invalidateTireViews(queryClient: ReturnType<typeof useQueryClient>, vin: string) {
  queryClient.invalidateQueries({ queryKey: ['tires', vin] })
  queryClient.invalidateQueries({ queryKey: ['reminders', vin] })
}

/**
 * Create a tire WITHOUT mounting it: it goes straight to storage.
 *
 * Replaced `useUpsertTire`. Before v3.3.0 `POST /tires` carried a position and
 * upserted by it, so there was no way to own a tire that was off the vehicle.
 * The endpoint now rejects a payload carrying `position` with a 422 rather
 * than silently creating a second, unmounted tire.
 */
export function useCreateTire(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (payload: TireCreate) => {
      const { data } = await api.post<Tire>(`/vehicles/${vin}/tires`, payload)
      return data
    },
    onSuccess: () => invalidateTireViews(queryClient, vin),
  })
}

/** Create a tire and mount it, atomically. 409 if the corner is occupied. */
export function useCreateAndMountTire(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (payload: TireCreateAndMountRequest) => {
      const { data } = await api.post<Tire>(`/vehicles/${vin}/tires/create-and-mount`, payload)
      return data
    },
    onSuccess: () => invalidateTireViews(queryClient, vin),
  })
}

export function useUpdateTire(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ tireId, ...payload }: TireUpdate & { tireId: number }) => {
      const { data } = await api.put<Tire>(`/vehicles/${vin}/tires/${tireId}`, payload)
      return data
    },
    onSuccess: () => invalidateTireViews(queryClient, vin),
  })
}

export function useMountTire(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ tireId, ...payload }: TireMountRequest & { tireId: number }) => {
      const { data } = await api.post<Tire>(`/vehicles/${vin}/tires/${tireId}/mount`, payload)
      return data
    },
    onSuccess: () => invalidateTireViews(queryClient, vin),
  })
}

export function useDismountTire(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ tireId, ...payload }: TireDismountRequest & { tireId: number }) => {
      const { data } = await api.post<Tire>(`/vehicles/${vin}/tires/${tireId}/dismount`, payload)
      return data
    },
    onSuccess: () => invalidateTireViews(queryClient, vin),
  })
}

/**
 * Retire a tire: off the vehicle, history kept.
 *
 * This is what replacing a worn tire means, and it is deliberately a different
 * mutation from `useDeleteTire`, which destroys every reading and mount period.
 */
export function useRetireTire(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ tireId, ...payload }: TireDismountRequest & { tireId: number }) => {
      const { data } = await api.post<Tire>(`/vehicles/${vin}/tires/${tireId}/retire`, payload)
      return data
    },
    onSuccess: () => invalidateTireViews(queryClient, vin),
  })
}

/** Move several tires at once. All or nothing. */
export function useRotateTires(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (payload: TireRotationRequest) => {
      const { data } = await api.post<TireListResponse>(`/vehicles/${vin}/tires/rotate`, payload)
      return data
    },
    onSuccess: () => invalidateTireViews(queryClient, vin),
  })
}

export function useAddTireReading(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ tireId, ...payload }: TireReadingCreate & { tireId: number }) => {
      const { data } = await api.post<Tire>(
        `/vehicles/${vin}/tires/${tireId}/readings`,
        payload
      )
      return data
    },
    onSuccess: () => invalidateTireViews(queryClient, vin),
  })
}

export function useDeleteTire(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (tireId: number) => {
      await api.delete(`/vehicles/${vin}/tires/${tireId}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tires', vin] })
    },
  })
}
