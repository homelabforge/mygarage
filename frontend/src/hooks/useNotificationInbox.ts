import { useQuery, type UseQueryResult } from '@tanstack/react-query'
import api from '@/services/api'
import type { components } from '@/types/api.generated'

export type InboxItem = components['schemas']['InboxItem']

type InboxResponse = components['schemas']['InboxResponse']

/** A reading write moves reminders, so it marks this stale too. */
export const NOTIFICATION_INBOX_QUERY_KEY = ['notifications', 'inbox'] as const

/**
 * The bell's inbox: overdue and soon-due reminders across the garage. Polls
 * every 60 s, but only while the tab has focus (`refetchIntervalInBackground`
 * stays off, like `useReminders`). A failed poll keeps the last list.
 */
export function useNotificationInbox(): UseQueryResult<InboxItem[]> {
  return useQuery({
    queryKey: NOTIFICATION_INBOX_QUERY_KEY,
    queryFn: async (): Promise<InboxItem[]> =>
      (await api.get<InboxResponse>('/notifications/inbox')).data.items ?? [],
    refetchInterval: 60_000,
  })
}
