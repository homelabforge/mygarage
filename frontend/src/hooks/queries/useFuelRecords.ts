import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/services/api'
import type { FuelRecordListResponse } from '@/types/fuel'

export function useFuelRecords(vin: string, includeHauling: boolean) {
  return useQuery({
    queryKey: ['fuelRecords', vin, includeHauling],
    queryFn: async () => {
      const { data } = await api.get<FuelRecordListResponse>(
        `/vehicles/${vin}/fuel?include_hauling=${includeHauling}`
      )
      return data
    },
    enabled: !!vin,
  })
}

export function useDeleteFuelRecord(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (recordId: number) => {
      await api.delete(`/vehicles/${vin}/fuel/${recordId}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['fuelRecords', vin] })
    },
  })
}

interface ImportCSVResult {
  success_count: number
  skipped_count: number
  error_count: number
  errors: string[]
}

export function useImportFuelCSV(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (formData: FormData) => {
      const { data } = await api.post<ImportCSVResult>(
        `/import/vehicles/${vin}/fuel/csv`,
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
      queryClient.invalidateQueries({ queryKey: ['fuelRecords', vin] })
    },
  })
}
