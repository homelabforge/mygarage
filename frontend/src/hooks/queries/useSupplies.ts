import { useQuery, useMutation, useQueryClient, type QueryClient } from '@tanstack/react-query'
import api from '@/services/api'
import type {
  Supply,
  SupplyListResponse,
  SupplyCreate,
  SupplyUpdate,
  SupplyPurchase,
  SupplyPurchaseCreate,
  SupplyAdjustmentCreate,
  SupplyHistory,
  SupplyUsage,
  VehicleSupplyUsages,
} from '@/types/supplies'

// Every purchase/adjustment/receipt mutation invalidates both the supplies
// list and (when scoped to a supply) its ledger history — shared here so the
// 9 mutations below don't each repeat the same invalidateQueries pair.
function invalidateSupplies(queryClient: QueryClient, supplyId?: number): void {
  queryClient.invalidateQueries({ queryKey: ['supplies'] })
  if (supplyId !== undefined) {
    queryClient.invalidateQueries({ queryKey: ['supply-history', supplyId] })
  }
}

export function useSupplies(includeArchived?: boolean, vin?: string) {
  return useQuery({
    queryKey: ['supplies', { includeArchived, vin }],
    queryFn: async () => {
      const params: Record<string, string | boolean> = {}
      if (includeArchived !== undefined) {
        params.include_archived = includeArchived
      }
      if (vin) {
        params.vin = vin
      }
      const { data } = await api.get<SupplyListResponse>('/supplies', { params })
      return data
    },
  })
}

export function useCreateSupply() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (payload: SupplyCreate) => {
      const { data } = await api.post<Supply>('/supplies', payload)
      return data
    },
    onSuccess: () => invalidateSupplies(queryClient),
  })
}

export function useUpdateSupply() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, ...payload }: SupplyUpdate & { id: number }) => {
      const { data } = await api.patch<Supply>(`/supplies/${id}`, payload)
      return data
    },
    onSuccess: () => invalidateSupplies(queryClient),
  })
}

export function useDeleteSupply() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (supplyId: number) => {
      await api.delete(`/supplies/${supplyId}`)
    },
    onSuccess: () => invalidateSupplies(queryClient),
  })
}

export function useSupplyHistory(supplyId: number | undefined) {
  return useQuery({
    queryKey: ['supply-history', supplyId],
    queryFn: async () => {
      const { data } = await api.get<SupplyHistory>(`/supplies/${supplyId}/history`)
      return data
    },
    enabled: !!supplyId,
  })
}

export function useAddPurchase(supplyId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (payload: SupplyPurchaseCreate) => {
      const { data } = await api.post<SupplyPurchase>(
        `/supplies/${supplyId}/purchases`,
        payload
      )
      return data
    },
    onSuccess: () => invalidateSupplies(queryClient, supplyId),
  })
}

export function useDeletePurchase(supplyId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (purchaseId: number) => {
      await api.delete(`/supplies/${supplyId}/purchases/${purchaseId}`)
    },
    onSuccess: () => invalidateSupplies(queryClient, supplyId),
  })
}

export function useAddAdjustment(supplyId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (payload: SupplyAdjustmentCreate) => {
      const { data } = await api.post<SupplyUsage>(
        `/supplies/${supplyId}/adjustments`,
        payload
      )
      return data
    },
    onSuccess: () => invalidateSupplies(queryClient, supplyId),
  })
}

export function useDeleteAdjustment(supplyId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (usageId: number) => {
      await api.delete(`/supplies/${supplyId}/adjustments/${usageId}`)
    },
    onSuccess: () => invalidateSupplies(queryClient, supplyId),
  })
}

export function useUploadReceipt(supplyId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({
      purchaseId,
      formData,
    }: {
      purchaseId: number
      formData: FormData
    }) => {
      const { data } = await api.post(
        `/supplies/${supplyId}/purchases/${purchaseId}/receipt`,
        formData,
        { headers: { 'Content-Type': 'multipart/form-data' } }
      )
      return data
    },
    onSuccess: () => invalidateSupplies(queryClient, supplyId),
  })
}

export function useDeleteReceipt(supplyId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (purchaseId: number) => {
      await api.delete(`/supplies/${supplyId}/purchases/${purchaseId}/receipt`)
    },
    onSuccess: () => invalidateSupplies(queryClient, supplyId),
  })
}

export function useVehicleSupplyUsages(vin: string | undefined) {
  return useQuery({
    queryKey: ['vehicle-supply-usages', vin],
    queryFn: async () => {
      const { data } = await api.get<VehicleSupplyUsages>(`/vehicles/${vin}/supply-usages`)
      return data
    },
    enabled: !!vin,
  })
}
