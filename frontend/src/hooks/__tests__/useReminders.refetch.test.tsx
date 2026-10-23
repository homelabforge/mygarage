/**
 * FUEL-stale: a fill-up from Telegram or LiveLink moves a reminder with no
 * write in this tab, so the list polls at the bell's 60 s cadence, and only
 * while the tab is visible.
 */
import { describe, expect, it, vi } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'

import api from '@/services/api'
import { useReminders } from '../useReminders'

describe('useReminders polling (FUEL-stale)', () => {
  it('refetches every 60 s, never in the background', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: [] })
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const wrapper = ({ children }: { children: ReactNode }): ReactNode => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    )
    const { result } = renderHook(() => useReminders('V1', 'pending'), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))

    const query = client.getQueryCache().find({ queryKey: ['reminders', 'V1', 'pending'] })
    const options = query?.options as { refetchInterval?: unknown; refetchIntervalInBackground?: unknown }
    expect(options.refetchInterval).toBe(60_000)
    expect(options.refetchIntervalInBackground ?? false).toBe(false)
  })
})
