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
  TireSet,
  TireSetCreate,
  TireSetListResponse,
  TireSetMountRequest,
  TireSetUpdate,
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
/**
 * Invalidate everything a tire write can change.
 *
 * `tire-sets` is in here because set membership is DERIVED from
 * `tires.set_id`: filing a tire into a set is a PUT on the tire, and retiring,
 * mounting or deleting one moves the set's `tire_ids` and `mounted_count`
 * without touching the set row at all. Leaving it out meant a tire filed into
 * a set showed the set still reading "Tires: 0" until something else forced a
 * refetch -- caught by an end-to-end test, and invisible to the component
 * tests because they mock these hooks away.
 */
function invalidateTireViews(queryClient: ReturnType<typeof useQueryClient>, vin: string) {
  queryClient.invalidateQueries({ queryKey: ['tires', vin] })
  queryClient.invalidateQueries({ queryKey: ['reminders', vin] })
  queryClient.invalidateQueries({ queryKey: ['tire-sets', vin] })
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

/* --- Tire sets ---------------------------------------------------------
 *
 * A set is UX grouping only: no distance, wear or position figure reads
 * membership. What it buys is the fit below, which replaces four dismounts and
 * four mounts -- each carrying an odometer the user has to retype -- with one
 * call.
 *
 * These use `invalidateTireViews` like every other mutation here: it already
 * covers the set key, and a second helper that differed only in ORDER was one
 * edit away from the two drifting apart. */

export function useTireSets(vin: string) {
  return useQuery({
    queryKey: ['tire-sets', vin],
    queryFn: async () => {
      const { data } = await api.get<TireSetListResponse>(`/vehicles/${vin}/tire-sets`)
      return data
    },
    enabled: Boolean(vin),
  })
}

/** Name a new, empty set. Tires join it through `useUpdateTire`. */
export function useCreateTireSet(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (payload: TireSetCreate) => {
      const { data } = await api.post<TireSet>(`/vehicles/${vin}/tire-sets`, payload)
      return data
    },
    onSuccess: () => invalidateTireViews(queryClient, vin),
  })
}

export function useUpdateTireSet(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ setId, ...payload }: TireSetUpdate & { setId: number }) => {
      const { data } = await api.put<TireSet>(`/vehicles/${vin}/tire-sets/${setId}`, payload)
      return data
    },
    onSuccess: () => invalidateTireViews(queryClient, vin),
  })
}

/** Delete a set. Its tires survive, ungrouped. */
export function useDeleteTireSet(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (setId: number) => {
      await api.delete(`/vehicles/${vin}/tire-sets/${setId}`)
    },
    onSuccess: () => invalidateTireViews(queryClient, vin),
  })
}

/** Fit every tire in a set, each at the corner it was last on. */
export function useMountTireSet(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ setId, ...payload }: TireSetMountRequest & { setId: number }) => {
      const { data } = await api.post<TireListResponse>(
        `/vehicles/${vin}/tire-sets/${setId}/mount`,
        payload
      )
      return data
    },
    onSuccess: () => invalidateTireViews(queryClient, vin),
  })
}
