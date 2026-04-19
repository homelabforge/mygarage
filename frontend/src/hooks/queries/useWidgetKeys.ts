import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import api from '@/services/api'
import type {
  WidgetKeyCreate,
  WidgetKeyCreated,
  WidgetKeyList,
} from '@/types/widgetKey'

const WIDGET_KEYS_QK = ['widget-keys'] as const

/**
 * Detects the 400 body the backend returns when auth_mode=none, so the UI
 * can render a dedicated disabled state instead of a generic error.
 */
export function isAuthDisabledError(error: unknown): boolean {
  const err = error as { response?: { status?: number; data?: { detail?: { detail?: string } } } }
  return (
    err?.response?.status === 400 &&
    err?.response?.data?.detail?.detail === 'widget_keys_require_auth'
  )
}

export function useWidgetKeys() {
  return useQuery({
    queryKey: WIDGET_KEYS_QK,
    queryFn: async () => {
      const { data } = await api.get<WidgetKeyList>('/auth/me/widget-keys')
      return data
    },
    // Don't auto-retry on 400 — it's a config signal, not a transient failure.
    retry: (failureCount, error) => !isAuthDisabledError(error) && failureCount < 2,
  })
}

export function useCreateWidgetKey() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (payload: WidgetKeyCreate) => {
      const { data } = await api.post<WidgetKeyCreated>(
        '/auth/me/widget-keys',
        payload,
      )
      return data
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: WIDGET_KEYS_QK })
    },
  })
}

export function useRevokeWidgetKey() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (keyId: number) => {
      await api.delete(`/auth/me/widget-keys/${keyId}`)
      return keyId
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: WIDGET_KEYS_QK })
    },
  })
}
