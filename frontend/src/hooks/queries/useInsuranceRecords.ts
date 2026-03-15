import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/services/api'
import type { InsurancePolicy, InsurancePolicyCreate, InsurancePolicyUpdate } from '@/types/insurance'

export function useInsuranceRecords(vin: string) {
  return useQuery({
    queryKey: ['insurance', vin],
    queryFn: async () => {
      const { data } = await api.get<InsurancePolicy[]>(
        `/vehicles/${vin}/insurance`
      )
      return data
    },
    enabled: !!vin,
  })
}

export function useCreateInsuranceRecord(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (payload: InsurancePolicyCreate) => {
      const { data } = await api.post(`/vehicles/${vin}/insurance`, payload)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['insurance', vin] })
    },
  })
}

export function useUpdateInsuranceRecord(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, ...payload }: InsurancePolicyUpdate & { id: number }) => {
      const { data } = await api.put(`/vehicles/${vin}/insurance/${id}`, payload)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['insurance', vin] })
    },
  })
}

export function useDeleteInsuranceRecord(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (recordId: number) => {
      await api.delete(`/vehicles/${vin}/insurance/${recordId}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['insurance', vin] })
    },
  })
}
