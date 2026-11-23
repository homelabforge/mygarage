import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { render } from '../../../__tests__/test-utils'
import { expectSafeOverlay } from '../../../__tests__/safeOverlay'
import type { Vehicle } from '@/types/vehicle'

const post = vi.fn().mockResolvedValue({ data: {} })
vi.mock('@/services/api', () => ({ default: { post: (...a: unknown[]) => post(...a), delete: vi.fn() } }))
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }))

import VehicleRemoveModal from '../VehicleRemoveModal'

const vehicle = { vin: 'VIN00000000000001', nickname: 'Truck', year: 2019, make: 'Ram', model: '2500' } as Vehicle

function openArchiveForm(): void {
  render(<VehicleRemoveModal isOpen onClose={vi.fn()} vehicle={vehicle} onConfirm={vi.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: /modal\.archiveRecommended/ }))
}

const archive = (): void => {
  fireEvent.click(screen.getByRole('button', { name: /modal\.archiveVehicle/ }))
}

beforeEach(() => vi.clearAllMocks())

// money-fits: the API takes a sale price from 0 to MONEY_MAX
// (9,999,999,999.99). Past it, or below 0, the archive used to come back a
// 422 toast; unreadable text was posted as null.
describe('VehicleRemoveModal: the archive sale price', () => {
  it.each([
    ['10000000000', 'common:validation.amount.tooLarge'],
    ['-5', 'common:validation.amount.negative'],
    ['abc', 'common:validation.amount.invalid'],
  ])('refuses %s on the field and posts nothing', async (typed, message) => {
    openArchiveForm()
    fireEvent.change(screen.getByLabelText(/modal\.salePrice/), { target: { value: typed } })
    archive()

    expect(await screen.findByText(message)).toBeInTheDocument()
    expect(post).not.toHaveBeenCalled()
  })

  it('the sale price error clears when the price is edited', async () => {
    openArchiveForm()
    const price = screen.getByLabelText(/modal\.salePrice/)
    fireEvent.change(price, { target: { value: '-5' } })
    archive()
    expect(await screen.findByText('common:validation.amount.negative')).toBeInTheDocument()

    fireEvent.change(price, { target: { value: '25000' } })
    expect(screen.queryByText('common:validation.amount.negative')).not.toBeInTheDocument()
    expect(price).not.toHaveAttribute('aria-invalid')
    expect(post).not.toHaveBeenCalled()
  })

  it('posts MONEY_MAX itself as a number', async () => {
    openArchiveForm()
    fireEvent.change(screen.getByLabelText(/modal\.salePrice/), { target: { value: '9999999999.99' } })
    archive()

    await waitFor(() => expect(post).toHaveBeenCalledTimes(1))
    expect((post.mock.calls[0][1] as { sale_price: unknown }).sale_price).toBe(9999999999.99)
  })

  it('posts a blank sale price as null', async () => {
    openArchiveForm()
    archive()

    await waitFor(() => expect(post).toHaveBeenCalledTimes(1))
    expect((post.mock.calls[0][1] as { sale_price: unknown }).sale_price).toBeNull()
  })

  it('posts no sale price or date once the reason hides them', async () => {
    // What was typed under Sold stays in state after a switch to Totaled. The
    // check skipped the hidden field but the post still sent it, so -5 was a 422.
    openArchiveForm()
    fireEvent.change(screen.getByLabelText(/modal\.salePrice/), { target: { value: '-5' } })
    fireEvent.change(document.querySelector('input[type="date"]')!, { target: { value: '2026-01-15' } })
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'Totaled' } })
    archive()

    await waitFor(() => expect(post).toHaveBeenCalledTimes(1))
    const body = post.mock.calls[0][1] as { reason: unknown; sale_price: unknown; sale_date: unknown }
    expect(body.reason).toBe('Totaled')
    expect(body.sale_price).toBeNull()
    expect(body.sale_date).toBeNull()
    expect(screen.queryByText('common:validation.amount.negative')).not.toBeInTheDocument()
  })
})

describe('VehicleRemoveModal layout', () => {
  it('centres inside the iPhone safe area (#305)', () => {
    render(<VehicleRemoveModal isOpen onClose={vi.fn()} vehicle={vehicle} onConfirm={vi.fn()} />)
    expectSafeOverlay(screen.getByRole('heading', { name: 'modal.removeVehicle' }))
  })
})
