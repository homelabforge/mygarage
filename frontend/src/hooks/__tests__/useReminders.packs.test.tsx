/**
 * A vehicle with no type asks for every pack: null goes to the service as is,
 * and the cache key reads it as ''.
 */
import { describe, expect, it, vi } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'

import { reminderService } from '@/services/reminderService'
import { useReminderPacks } from '../useReminders'

describe('useReminderPacks with no vehicle type', () => {
  it('passes null to the service under the empty key', async () => {
    const listPacks = vi.spyOn(reminderService, 'listPacks').mockResolvedValue([])
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const wrapper = ({ children }: { children: ReactNode }): ReactNode => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    )
    const { result } = renderHook(() => useReminderPacks(null), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))

    // Pins out a hook that swaps in a default type, or keys null apart from ''.
    expect(listPacks.mock.calls).toEqual([[null]])
    expect(client.getQueryCache().find({ queryKey: ['reminderPacks', ''], exact: true })).toBeDefined()
    listPacks.mockRestore()
  })
})
