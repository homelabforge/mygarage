import { describe, it, expect, vi } from 'vitest'
import { dropQueuedOnces } from './serverErrors'

describe('dropQueuedOnces', () => {
  it('drops a rejection a test queued and never used, and keeps the default', async () => {
    const save = vi.fn().mockResolvedValue('saved')
    const afterEachHook = dropQueuedOnces(save)
    save.mockRejectedValueOnce(new Error('queued 422'))
    // What every file's beforeEach already does, and it keeps the queue.
    vi.clearAllMocks()

    afterEachHook()

    await expect(save()).resolves.toBe('saved')
  })

  it('leaves a mock that had no default with none', () => {
    const lookup = vi.fn()
    const afterEachHook = dropQueuedOnces(lookup)
    lookup.mockReturnValueOnce('queued')

    afterEachHook()

    expect(lookup()).toBeUndefined()
  })
})
