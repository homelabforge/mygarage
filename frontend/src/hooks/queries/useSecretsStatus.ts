import { useQuery, type UseQueryResult } from '@tanstack/react-query'
import api from '@/services/api'
import type { components } from '@/types/api.generated'

export type SecretsStatus = components['schemas']['SecretsStatusResponse']

/** Invalidate this after a write that can store a secret, so the banner catches up. */
export const SECRETS_STATUS_QUERY_KEY = ['settings', 'secrets-status'] as const

/**
 * GET /settings/secrets/status. Admin-only on the server, so only mount a
 * reader of this for someone who can manage the instance. Invalidating the key
 * for a non-admin fetches nothing, since only a mounted reader refetches.
 */
export function useSecretsStatus(): UseQueryResult<SecretsStatus> {
  return useQuery({
    queryKey: SECRETS_STATUS_QUERY_KEY,
    queryFn: async (): Promise<SecretsStatus> =>
      (await api.get<SecretsStatus>('/settings/secrets/status')).data,
    // Read fresh on every visit to Settings, like it was before the cache, and
    // drop the answer on leaving: a secret re-entered elsewhere (a POI provider)
    // doesn't mark it stale, so a kept list would flash it as unreadable.
    staleTime: 0,
    gcTime: 0,
    retry: false,
  })
}
