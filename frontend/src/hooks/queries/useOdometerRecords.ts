import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/services/api'
import { invalidateReadingViews } from '@/hooks/useReminders'
import type {
  OdometerRecordListResponse,
  OdometerRecordCreate,
  OdometerRecordUpdate,
  NearestOdometer,
} from '@/types/odometer'

export function useOdometerRecords(vin: string) {
  return useQuery({
    queryKey: ['odometerRecords', vin],
    queryFn: async () => {
      const { data } = await api.get<OdometerRecordListResponse>(
        `/vehicles/${vin}/odometer`
      )
      return data
    },
    enabled: !!vin,
  })
}

export function useCreateOdometerRecord(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (payload: OdometerRecordCreate) => {
      const { data } = await api.post(`/vehicles/${vin}/odometer`, payload)
      return data
    },
    onSuccess: () => {
      invalidateReadingViews(queryClient, vin)
    },
  })
}

export function useUpdateOdometerRecord(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, ...payload }: OdometerRecordUpdate & { id: number }) => {
      const { data } = await api.put(`/vehicles/${vin}/odometer/${id}`, payload)
      return data
    },
    onSuccess: () => {
      invalidateReadingViews(queryClient, vin)
    },
  })
}

export function useDeleteOdometerRecord(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (recordId: number) => {
      await api.delete(`/vehicles/${vin}/odometer/${recordId}`)
    },
    onSuccess: () => {
      invalidateReadingViews(queryClient, vin)
    },
  })
}

interface ImportCSVResult {
  success_count: number
  skipped_count: number
  error_count: number
  errors: string[]
}

export function useImportOdometerCSV(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (formData: FormData) => {
      const { data } = await api.post<ImportCSVResult>(
        `/import/vehicles/${vin}/odometer/csv`,
        formData,
        {
          headers: {
            'Content-Type': 'multipart/form-data',
          },
        }
      )
      return data
    },
    onSuccess: () => {
      invalidateReadingViews(queryClient, vin)
    },
  })
}

/**
 * The vehicle's odometer reading nearest to a date, for the suggestion under
 * every tire dialog's odometer field.
 *
 * Under the `['odometerRecords', vin]` prefix on purpose: every tire mutation
 * invalidates that prefix, so a suggestion can never offer a value a mount,
 * an edit or a delete just changed. 404 means the vehicle has no readings,
 * which is an answer the field renders, not an error, so it resolves to null
 * rather than throwing; `retry: false` for the same reason.
 */
export function useNearestOdometer(vin: string, date: string) {
  return useQuery({
    queryKey: ['odometerRecords', vin, 'nearest', date],
    queryFn: async (): Promise<NearestOdometer | null> => {
      try {
        const { data } = await api.get<NearestOdometer>(`/vehicles/${vin}/odometer/nearest`, {
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
