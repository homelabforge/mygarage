import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/services/api'
import type {
  TollTransactionListResponse,
  TollTagListResponse,
  TollTransactionSummary,
} from '@/types/toll'

export function useTollTransactions(vin: string) {
  return useQuery({
    queryKey: ['tollTransactions', vin],
    queryFn: async () => {
      const { data } = await api.get<TollTransactionListResponse>(
        `/vehicles/${vin}/toll-transactions`
      )
      return data
    },
    enabled: !!vin,
  })
}

export function useTollTransactionSummary(vin: string) {
  return useQuery({
    queryKey: ['tollTransactionSummary', vin],
    queryFn: async () => {
      const { data } = await api.get<TollTransactionSummary>(
        `/vehicles/${vin}/toll-transactions/summary/statistics`
      )
      return data
    },
    enabled: !!vin,
  })
}

export function useTollTags(vin: string) {
  return useQuery({
    queryKey: ['tollTags', vin],
    queryFn: async () => {
      const { data } = await api.get<TollTagListResponse>(
        `/vehicles/${vin}/toll-tags`
      )
      return data
    },
    enabled: !!vin,
  })
}

export function useDeleteTollTransaction(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (transactionId: number) => {
      await api.delete(`/vehicles/${vin}/toll-transactions/${transactionId}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tollTransactions', vin] })
      queryClient.invalidateQueries({ queryKey: ['tollTransactionSummary', vin] })
    },
  })
}
