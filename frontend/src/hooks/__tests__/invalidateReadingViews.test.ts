import { describe, expect, it, vi } from 'vitest'
import { QueryClient } from '@tanstack/react-query'

import { invalidateReadingViews } from '../useReminders'

describe('invalidateReadingViews', () => {
  it('refreshes the tire list, whose open periods end at the current reading (#217)', () => {
    const client = new QueryClient()
    const invalidate = vi.spyOn(client, 'invalidateQueries')
    invalidateReadingViews(client, 'V1')
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['tires', 'V1'] })
    // The keys it already refreshed stay.
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['hoursRecords', 'V1'] })
  })
})
