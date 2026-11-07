import { useQuery } from '@tanstack/react-query'
import api from '@/services/api'
import { isAuthError, isPermissionError } from '@/utils/httpErrorHandler'
import type { components } from '@/types/api.generated'

export type TelegramFuelStatus = components['schemas']['TelegramFuelStatus']

const POLL_MS = 15_000

/**
 * Poll every 15 s, but not after a 401 or 403: asking again won't change a
 * refusal (G5b-66). Any other failure keeps polling, since an outage passes.
 */
export function fuelStatusInterval(error: unknown): number | false {
  return isAuthError(error) || isPermissionError(error) ? false : POLL_MS
}

/**
 * The Telegram fuel-command poller's state. Admin-only on the server.
 * `retry: false` so a refusal is not repeated: an explicit query option wins
 * over the client default (`retry: 1` in App.tsx, `retry: false` in tests).
 */
export function useTelegramFuelStatus() {
  return useQuery({
    queryKey: ['telegram-fuel-status'],
    queryFn: async (): Promise<TelegramFuelStatus> => {
      const { data } = await api.get<TelegramFuelStatus>('/notifications/telegram/fuel-commands')
      return data
    },
    refetchInterval: (query) => fuelStatusInterval(query.state.error),
    retry: false,
  })
}
