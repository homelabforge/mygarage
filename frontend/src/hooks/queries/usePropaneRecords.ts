import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/services/api'
import type { FuelRecord, FuelRecordListResponse } from '@/types/fuel'

export function usePropaneRecords(vin: string) {
  return useQuery({
    queryKey: ['propaneRecords', vin],
    queryFn: async () => {
      const { data } = await api.get<FuelRecordListResponse>(
        `/vehicles/${vin}/fuel`
      )
      // Filter to only records with propane_gallons and no regular gallons
      const propaneRecords = (data.records || []).filter((r: FuelRecord) => {
        const propaneGallons = typeof r.propane_gallons === 'string' ? parseFloat(r.propane_gallons) : r.propane_gallons
        return propaneGallons && propaneGallons > 0 && !r.gallons
      })
      return { records: propaneRecords, total: propaneRecords.length }
    },
    enabled: !!vin,
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
