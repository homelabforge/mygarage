import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/services/api'
import { invalidateReadingViews } from '@/hooks/useReminders'
import type {
  HoursRecordListResponse,
  HoursRecordCreate,
  HoursRecordUpdate,
  NearestHours,
} from '@/types/hours'

/**
 * Engine-hours analog of hooks/queries/useOdometerRecords.ts
 * (s/odometer_km/engine_hours/, s/odometer/hours/). Engine hours are
 * dimensionless -- no unit conversion anywhere, unlike odometer's km<->mi.
 */
export function useHoursRecords(vin: string) {
  return useQuery({
    queryKey: ['hoursRecords', vin],
    queryFn: async () => {
      const { data } = await api.get<HoursRecordListResponse>(
        `/vehicles/${vin}/hours`
      )
      return data
    },
    enabled: !!vin,
  })
}

export function useCreateHoursRecord(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (payload: HoursRecordCreate) => {
      const { data } = await api.post(`/vehicles/${vin}/hours`, payload)
      return data
    },
    onSuccess: () => {
      invalidateReadingViews(queryClient, vin)
    },
  })
}

export function useUpdateHoursRecord(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, ...payload }: HoursRecordUpdate & { id: number }) => {
      const { data } = await api.put(`/vehicles/${vin}/hours/${id}`, payload)
      return data
    },
    onSuccess: () => {
      invalidateReadingViews(queryClient, vin)
    },
  })
}

export function useDeleteHoursRecord(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (recordId: number) => {
      await api.delete(`/vehicles/${vin}/hours/${recordId}`)
    },
    onSuccess: () => {
      invalidateReadingViews(queryClient, vin)
    },
  })
}

/**
 * The vehicle's hours reading nearest to a date, for the hour meter field on
 * every tire dialog. Under the `['hoursRecords', vin]` prefix so every reading
 * write refreshes it; a 404 means no readings yet and resolves to null.
 */
export function useNearestHours(vin: string, date: string) {
  return useQuery({
    queryKey: ['hoursRecords', vin, 'nearest', date],
    queryFn: async (): Promise<NearestHours | null> => {
      try {
        const { data } = await api.get<NearestHours>(`/vehicles/${vin}/hours/nearest`, {
          params: { date },
        })
        return data
      } catch (err) {
        const status = (err as { response?: { status?: number } }).response?.status
        if (status === 404) return null
        throw err
      }
    },
    enabled: Boolean(vin) && /^\d{4}-\d{2}-\d{2}$/.test(date),
    retry: false,
  })
}
