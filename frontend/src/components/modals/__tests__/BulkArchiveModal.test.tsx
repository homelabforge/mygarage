import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { render } from '../../../__tests__/test-utils'

const post = vi.fn().mockResolvedValue({ data: {} })
vi.mock('@/services/api', () => ({ default: { post: (...a: unknown[]) => post(...a) } }))
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }))

import BulkArchiveModal from '../BulkArchiveModal'

const PROPS = {
  isOpen: true,
  vins: ['VIN00000000000001', 'VIN00000000000002'],
  onClose: vi.fn(),
  onConfirm: vi.fn(),
}

beforeEach(() => vi.clearAllMocks())

describe('BulkArchiveModal', () => {
  it('archives as VISIBLE by default, matching the single-vehicle flow', async () => {
    // VehicleRemoveModal defaults visible to true and the backend's
    // VehicleArchiveRequest declares visible=True. Defaulting to false here
    // meant archiving one sold car left it on the dashboard while bulk-archiving
    // three made them vanish: same action, opposite result, decided only by
    // which entry point the user happened to use.
    render(<BulkArchiveModal {...PROPS} />)

    fireEvent.click(screen.getByRole('button', { name: /archive/i }))

    await waitFor(() => expect(post).toHaveBeenCalled())
    for (const call of post.mock.calls) {
      expect((call[1] as { visible?: boolean }).visible).toBe(true)
    }
  })

  it('renders over a translucent backdrop, not an opaque one', () => {
    // bg-opacity-50 was removed in Tailwind v4 and this project is on v4, so it
    // emitted no CSS at all and bg-black painted a solid sheet over the page.
    const { container } = render(<BulkArchiveModal {...PROPS} />)
    const backdrop = container.querySelector('.fixed.inset-0')

    expect(backdrop?.className).toContain('bg-black/50')
    expect(backdrop?.className).not.toContain('bg-opacity-')
  })
})
