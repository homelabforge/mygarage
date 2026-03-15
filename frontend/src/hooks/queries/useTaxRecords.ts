import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/services/api'
import type { TaxRecordListResponse, TaxRecordCreate, TaxRecordUpdate } from '@/types/tax'

export function useTaxRecords(vin: string) {
  return useQuery({
    queryKey: ['taxRecords', vin],
    queryFn: async () => {
      const { data } = await api.get<TaxRecordListResponse>(
        `/vehicles/${vin}/tax-records`
      )
      return data
    },
    enabled: !!vin,
  })
}

export function useCreateTaxRecord(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (payload: TaxRecordCreate) => {
      const { data } = await api.post(`/vehicles/${vin}/tax-records`, payload)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['taxRecords', vin] })
    },
  })
}

export function useUpdateTaxRecord(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, ...payload }: TaxRecordUpdate & { id: number }) => {
      const { data } = await api.put(`/vehicles/${vin}/tax-records/${id}`, payload)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['taxRecords', vin] })
    },
  })
}

export function useDeleteTaxRecord(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (recordId: number) => {
      await api.delete(`/vehicles/${vin}/tax-records/${recordId}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['taxRecords', vin] })
    },
  })
}
