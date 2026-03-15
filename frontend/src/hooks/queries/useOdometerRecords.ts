import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/services/api'
import type { OdometerRecordListResponse, OdometerRecordCreate, OdometerRecordUpdate } from '@/types/odometer'

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
      queryClient.invalidateQueries({ queryKey: ['odometerRecords', vin] })
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
      queryClient.invalidateQueries({ queryKey: ['odometerRecords', vin] })
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
      queryClient.invalidateQueries({ queryKey: ['odometerRecords', vin] })
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
      queryClient.invalidateQueries({ queryKey: ['odometerRecords', vin] })
    },
  })
}
