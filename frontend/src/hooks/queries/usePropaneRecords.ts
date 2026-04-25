import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/services/api'
import type { FuelRecord, FuelRecordListResponse, FuelRecordCreate, FuelRecordUpdate } from '@/types/fuel'

export function usePropaneRecords(vin: string) {
  return useQuery({
    queryKey: ['propaneRecords', vin],
    queryFn: async () => {
      const { data } = await api.get<FuelRecordListResponse>(
        `/vehicles/${vin}/fuel`
      )
      // Filter to only records with propane_liters and no regular liters
      const propaneRecords = (data.records || []).filter((r: FuelRecord) => {
        const propaneLiters = typeof r.propane_liters === 'string' ? parseFloat(r.propane_liters) : r.propane_liters
        return propaneLiters && propaneLiters > 0 && !r.liters
      })
      return { records: propaneRecords, total: propaneRecords.length }
    },
    enabled: !!vin,
  })
}

export function useCreatePropaneRecord(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (payload: FuelRecordCreate) => {
      const { data } = await api.post(`/vehicles/${vin}/fuel`, payload)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['propaneRecords', vin] })
      queryClient.invalidateQueries({ queryKey: ['fuelRecords', vin] })
    },
  })
}

export function useUpdatePropaneRecord(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, ...payload }: FuelRecordUpdate & { id: number }) => {
      const { data } = await api.put(`/vehicles/${vin}/fuel/${id}`, payload)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['propaneRecords', vin] })
      queryClient.invalidateQueries({ queryKey: ['fuelRecords', vin] })
    },
  })
}

export function useDeletePropaneRecord(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (recordId: number) => {
      await api.delete(`/vehicles/${vin}/fuel/${recordId}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['propaneRecords', vin] })
      queryClient.invalidateQueries({ queryKey: ['fuelRecords', vin] })
    },
  })
}
