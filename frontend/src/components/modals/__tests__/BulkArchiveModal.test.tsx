import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
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

  it('is still VISIBLE by default after a cancel and reopen', async () => {
    // resetForm put visible back to false, so only the first bulk archive of a
    // session got the default the test above pins.
    render(<BulkArchiveModal {...PROPS} />)
    fireEvent.click(screen.getByRole('button', { name: 'common:cancel' }))
    fireEvent.click(screen.getByRole('button', { name: /archive/i }))

    await waitFor(() => expect(post).toHaveBeenCalled())
    expect((post.mock.calls[0][1] as { visible?: boolean }).visible).toBe(true)
  })

  // money-fits: the API takes a sale price from 0 to MONEY_MAX
  // (9,999,999,999.99). The field is optional; blank posts null.
  it.each([
    ['10000000000', 'common:validation.amount.tooLarge'],
    ['-5', 'common:validation.amount.negative'],
    ['abc', 'common:validation.amount.invalid'],
  ])('refuses a sale price of %s on the field and posts nothing', async (typed, message) => {
    render(<BulkArchiveModal {...PROPS} />)
    fireEvent.change(screen.getByLabelText(/modal\.salePrice/), { target: { value: typed } })
    fireEvent.click(screen.getByRole('button', { name: /archive/i }))

    expect(await screen.findByText(message)).toBeInTheDocument()
    expect(post).not.toHaveBeenCalled()
  })

  it('the sale price error clears when the price is edited', async () => {
    render(<BulkArchiveModal {...PROPS} />)
    const price = screen.getByLabelText(/modal\.salePrice/)
    fireEvent.change(price, { target: { value: '-5' } })
    fireEvent.click(screen.getByRole('button', { name: /archive/i }))
    expect(await screen.findByText('common:validation.amount.negative')).toBeInTheDocument()

    fireEvent.change(price, { target: { value: '25000' } })
    expect(screen.queryByText('common:validation.amount.negative')).not.toBeInTheDocument()
    expect(price).not.toHaveAttribute('aria-invalid')
    expect(post).not.toHaveBeenCalled()
  })

  it('posts a typed sale price as a number', async () => {
    render(<BulkArchiveModal {...PROPS} />)
    fireEvent.change(screen.getByLabelText(/modal\.salePrice/), { target: { value: '25000' } })
    fireEvent.click(screen.getByRole('button', { name: /archive/i }))
    await waitFor(() => expect(post).toHaveBeenCalled())
    expect((post.mock.calls[0][1] as { sale_price: unknown }).sale_price).toBe(25000)
  })

  it('posts no sale price or date once the reason hides them', async () => {
    // What was typed under Sold stays in state after a switch to Totaled. The
    // check skipped the hidden field but the post still sent it, so -5 was a 422.
    render(<BulkArchiveModal {...PROPS} />)
    fireEvent.change(screen.getByLabelText(/modal\.salePrice/), { target: { value: '-5' } })
    fireEvent.change(document.querySelector('input[type="date"]')!, { target: { value: '2026-01-15' } })
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'Totaled' } })
    fireEvent.click(screen.getByRole('button', { name: /archive/i }))

    await waitFor(() => expect(post).toHaveBeenCalledTimes(1))
    const body = post.mock.calls[0][1] as { reason: unknown; sale_price: unknown; sale_date: unknown }
    expect(body.reason).toBe('Totaled')
    expect(body.sale_price).toBeNull()
    expect(body.sale_date).toBeNull()
    expect(screen.queryByText('common:validation.amount.negative')).not.toBeInTheDocument()
  })

  it('renders over a translucent backdrop, not an opaque one', () => {
    // bg-opacity-50 was removed in Tailwind v4 and this project is on v4, so it
    // emitted no CSS at all and bg-black painted a solid sheet over the page.
    render(<BulkArchiveModal {...PROPS} />)
    const backdrop = screen.getByRole('dialog').parentElement

    expect(backdrop?.className).toContain('bg-black/50')
    expect(backdrop?.className).not.toContain('bg-opacity-')
  })
})

describe('BulkArchiveModal as a dialog', () => {
  let root: HTMLElement
  beforeEach(() => {
    root = document.body.appendChild(document.createElement('div'))
    root.id = 'root'
  })
  afterEach(() => root.remove())

  it('is a named dialog outside #root', () => {
    render(<BulkArchiveModal {...PROPS} />, { container: root })
    const dialog = screen.getByRole('dialog', { name: 'modal.bulkArchiveTitle' })
    expect(root.contains(dialog)).toBe(false)
  })
})
