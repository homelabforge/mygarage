import { useQuery, useMutation, useQueryClient, type QueryClient } from '@tanstack/react-query'
import api from '@/services/api'
import type {
  InsurancePolicy,
  InsurancePolicyCreate,
  InsurancePolicyRenew,
  InsurancePolicyReplace,
  InsurancePolicyUpdate,
  PolicyHistoryEntry,
  PolicyStatusFilter,
  PolicyVehicleCreate,
} from '@/types/insurance'

/** A policy is a household record: one change can alter what several vehicles'
 *  tabs, the Insurance page and a history drawer show, so every mutation
 *  invalidates the whole `insurance` key family rather than one vehicle's. */
function invalidateInsurance(queryClient: QueryClient): Promise<void> {
  return queryClient.invalidateQueries({ queryKey: ['insurance'] })
}

/** The household's policies, each with its vehicles beneath it. */
export function useInsurancePolicies(status: PolicyStatusFilter = 'current') {
  return useQuery({
    queryKey: ['insurance', 'policies', status],
    queryFn: async () => {
      const { data } = await api.get<InsurancePolicy[]>('/insurance/policies', {
        params: { status },
      })
      return data
    },
  })
}

/** Every policy, past and present, covering one vehicle. */
export function useInsuranceRecords(vin: string) {
  return useQuery({
    queryKey: ['insurance', 'vehicle', vin],
    queryFn: async () => {
      const { data } = await api.get<InsurancePolicy[]>(`/vehicles/${vin}/insurance`)
      return data
    },
    enabled: !!vin,
  })
}

export function usePolicyHistory(policyId: number | null) {
  return useQuery({
    queryKey: ['insurance', 'history', policyId],
    queryFn: async () => {
      const { data } = await api.get<PolicyHistoryEntry[]>(
        `/insurance/policies/${policyId}/history`
      )
      return data
    },
    enabled: policyId != null,
  })
}

export function useCreateInsurancePolicy() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (payload: InsurancePolicyCreate) => {
      const { data } = await api.post<InsurancePolicy>('/insurance/policies', payload)
      return data
    },
    onSuccess: () => invalidateInsurance(queryClient),
  })
}

export function useUpdateInsurancePolicy() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, ...payload }: InsurancePolicyUpdate & { id: number }) => {
      const { data } = await api.put<InsurancePolicy>(`/insurance/policies/${id}`, payload)
      return data
    },
    onSuccess: () => invalidateInsurance(queryClient),
  })
}

export function useDeleteInsurancePolicy() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (policyId: number) => {
      await api.delete(`/insurance/policies/${policyId}`)
    },
    onSuccess: () => invalidateInsurance(queryClient),
  })
}

export function useRenewInsurancePolicy() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, ...payload }: InsurancePolicyRenew & { id: number }) => {
      const { data } = await api.post<InsurancePolicy>(`/insurance/policies/${id}/renew`, payload)
      return data
    },
    onSuccess: () => invalidateInsurance(queryClient),
  })
}

export function useReplaceInsurancePolicy() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, ...payload }: InsurancePolicyReplace & { id: number }) => {
      const { data } = await api.post<InsurancePolicy>(`/insurance/policies/${id}/replace`, payload)
      return data
    },
    onSuccess: () => invalidateInsurance(queryClient),
  })
}

/** Put one more vehicle on an existing policy (the vehicle tab's shortcut). */
export function useAttachPolicyVehicle() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ policyId, ...payload }: PolicyVehicleCreate & { policyId: number }) => {
      const { data } = await api.post<InsurancePolicy>(
        `/insurance/policies/${policyId}/vehicles`,
        payload
      )
      return data
    },
    onSuccess: () => invalidateInsurance(queryClient),
  })
}
