import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/services/api'
import type { FuelRecordListResponse, FuelRecordCreate, FuelRecordUpdate } from '@/types/fuel'

export interface UseFuelRecordsOptions {
  /** Records to skip — backend pagination cursor. Default 0. */
  skip?: number
  /**
   * Page size. Backend caps at 500. Phase 3.8 (issue #69): rc1 hit the
   * server-side default of 100 with no UI indication; the new
   * FuelRecordList exposes prev/next paging on top of this hook.
   */
  limit?: number
}

export function useFuelRecords(
  vin: string,
  includeHauling: boolean,
  options: UseFuelRecordsOptions = {}
) {
  const { skip = 0, limit = 50 } = options
  return useQuery({
    queryKey: ['fuelRecords', vin, includeHauling, skip, limit],
    queryFn: async () => {
      const params = new URLSearchParams({
        include_hauling: String(includeHauling),
        skip: String(skip),
        limit: String(limit),
      })
      const { data } = await api.get<FuelRecordListResponse>(
        `/vehicles/${vin}/fuel?${params.toString()}`
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

export function useCreateFuelRecord(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (payload: FuelRecordCreate) => {
      const { data } = await api.post(`/vehicles/${vin}/fuel`, payload)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['fuelRecords', vin] })
    },
  })
}

export function useUpdateFuelRecord(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, ...payload }: FuelRecordUpdate & { id: number }) => {
      const { data } = await api.put(`/vehicles/${vin}/fuel/${id}`, payload)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['fuelRecords', vin] })
    },
  })
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
