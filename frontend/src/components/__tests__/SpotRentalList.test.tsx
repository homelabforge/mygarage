import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '../../__tests__/test-utils'
import { fireEvent } from '@testing-library/react'
import type { SpotRental, SpotRentalBilling } from '../../types/spotRental'

const useSpotRentalsMock = vi.fn()
const deleteMutate = vi.fn()
const apiDelete = vi.fn().mockResolvedValue({})
vi.mock('../../hooks/queries/useSpotRentals', () => ({
  useSpotRentals: () => useSpotRentalsMock(),
  useDeleteSpotRental: () => ({ mutate: deleteMutate, isPending: false, variables: undefined }),
}))
vi.mock('../../hooks/useCurrencyPreference', () => ({
  useCurrencyPreference: () => ({ currencyCode: 'USD', locale: 'en-US' }),
}))
vi.mock('../../services/api', () => ({ default: { delete: (...a: unknown[]) => apiDelete(...a) } }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
// Stub the child forms to observe add-vs-edit routing without mounting the real Drawers.
vi.mock('../SpotRentalForm', () => ({
  default: (props: { rental?: { id: number } }) => <div data-testid="spot-rental-form">form:{props.rental ? props.rental.id : 'new'}</div>,
}))
vi.mock('../BillingEntryForm', () => ({
  default: (props: { rentalId: number; billing?: { id: number } }) => (
    <div data-testid="billing-form">billing:{props.rentalId}:{props.billing ? props.billing.id : 'new'}</div>
  ),
}))

import SpotRentalList from '../SpotRentalList'
import { answerConfirm } from '../../__tests__/confirmHelpers'

const billing = {
  id: 90, spot_rental_id: 1, billing_date: '2026-03-01',
  monthly_rate: '100', electric: '10', water: '5', waste: '5', total: '120',
  notes: null, created_at: '2026-03-01T00:00:00',
} as unknown as SpotRentalBilling
// B6: a SECOND billing so billingCount > 1 — the expand/collapse disclosure (rendered only when >1) actually
// exists, so its toggle / expanded rows / billing edit+delete paths can be driven.
const billing2 = {
  id: 91, spot_rental_id: 1, billing_date: '2026-02-01',
  monthly_rate: '100', electric: '8', water: '4', waste: '4', total: '116',
  notes: null, created_at: '2026-02-01T00:00:00',
} as unknown as SpotRentalBilling
const activeRental = {
  id: 1, vin: 'V1', location_name: 'Lakeside', location_address: '123 Rd',
  check_in_date: '2026-03-01', check_out_date: null,
  nightly_rate: null, weekly_rate: null, monthly_rate: '100',
  electric: null, water: null, waste: null, total_cost: null,
  amenities: null, notes: null, billings: [billing, billing2], created_at: '2026-03-01T00:00:00',
} as unknown as SpotRental
const closedRental = {
  ...activeRental, id: 2, location_name: 'Riverside', check_out_date: '2026-04-01', billings: [],
} as unknown as SpotRental

beforeEach(() => {
  vi.clearAllMocks()
  useSpotRentalsMock.mockReturnValue({ data: { spot_rentals: [activeRental] }, isLoading: false, error: null })
})

describe('SpotRentalList — rendering + row actions', () => {
  it('renders the list heading and a rental location (fails if the h3 title or the location is dropped)', () => {
    render(<SpotRentalList vin="V1" />)
    expect(screen.getByRole('heading', { name: 'spotRentalList.title' })).toBeInTheDocument()
    expect(screen.getByText('Lakeside')).toBeInTheDocument()
  })

  it('the rental-count summary phrase renders inside its OWN element (the <Mono> wrap, B9) — fails if the count is left as bare text concatenated into the summary <p>', () => {
    render(<SpotRentalList vin="V1" />)
    // The i18n mock echoes keys, so t('spotRentalList.rentalCount', {count}) resolves to the exact key. TL's
    // getNodeText reads only DIRECT text children, so an EXACT getByText match resolves ONLY when the phrase sits
    // in its own element (the <Mono> span). Left as bare text in the <p>, it would be concatenated with the
    // 'active'/'totalSpent' fragments and this exact match would fail — so this discriminates the Mono wrap.
    expect(screen.getByText('spotRentalList.rentalCount')).toBeInTheDocument()
  })

  it('clicking Add mounts SpotRentalForm with NO rental (create), not an edit (fails if Add is unwired or seeds a rental)', () => {
    render(<SpotRentalList vin="V1" />)
    expect(screen.queryByTestId('spot-rental-form')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'spotRentalList.addRental' }))
    expect(screen.getByTestId('spot-rental-form')).toHaveTextContent('form:new')
  })

  it('clicking row Edit mounts SpotRentalForm with THAT rental (fails if edit is unwired or passes the wrong row)', () => {
    render(<SpotRentalList vin="V1" />)
    fireEvent.click(screen.getByRole('button', { name: 'spotRentalList.editRental' }))
    expect(screen.getByTestId('spot-rental-form')).toHaveTextContent('form:1')
  })

  it('clicking row Delete (confirm accepted) calls the delete mutation with the rental id (fails if delete is unwired or the confirm gate is dropped)', async () => {
    render(<SpotRentalList vin="V1" />)
    fireEvent.click(screen.getByRole('button', { name: 'spotRentalList.deleteRental' }))
    await answerConfirm('confirm', 'spotRentalList.confirmDelete')
    expect(deleteMutate).toHaveBeenCalledWith(1, expect.anything())
  })

  it('clicking row Delete with confirm REJECTED does NOT call the delete mutation (fails if the handler ignores a false confirm)', async () => {
    render(<SpotRentalList vin="V1" />)
    fireEvent.click(screen.getByRole('button', { name: 'spotRentalList.deleteRental' }))
    await answerConfirm('cancel', 'spotRentalList.confirmDelete')
    expect(deleteMutate).not.toHaveBeenCalled()
  })

  it('the row Edit/Delete expose a real aria-label (IconButton), not a bare title (fails if IconButton regresses to a title-only <button>)', () => {
    render(<SpotRentalList vin="V1" />)
    expect(screen.getByRole('button', { name: 'spotRentalList.editRental' })).toHaveAttribute('aria-label', 'spotRentalList.editRental')
    expect(screen.getByRole('button', { name: 'spotRentalList.deleteRental' })).toHaveAttribute('aria-label', 'spotRentalList.deleteRental')
  })
})

describe('SpotRentalList — status (both ways) + empty + billing', () => {
  it('an active rental (no check-out) shows the Active chip (fails if the active marker stops rendering)', () => {
    render(<SpotRentalList vin="V1" />)
    expect(screen.getByText('spotRentalList.activeStatus')).toBeInTheDocument()
  })

  it('a closed rental (check-out present) shows NO Active chip (fails if the status is hardcoded to always-active)', () => {
    useSpotRentalsMock.mockReturnValue({ data: { spot_rentals: [closedRental] }, isLoading: false, error: null })
    render(<SpotRentalList vin="V1" />)
    expect(screen.getByText('Riverside')).toBeInTheDocument()
    expect(screen.queryByText('spotRentalList.activeStatus')).not.toBeInTheDocument()
  })

  it('with zero rentals, the empty-state CTA mounts SpotRentalForm (fails if the CTA is unwired or the title text changes)', () => {
    useSpotRentalsMock.mockReturnValue({ data: { spot_rentals: [] }, isLoading: false, error: null })
    render(<SpotRentalList vin="V1" />)
    expect(screen.getByText('spotRentalList.noRecords')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'spotRentalList.addFirstRental' }))
    expect(screen.getByTestId('spot-rental-form')).toHaveTextContent('form:new')
  })

  it('clicking Add Billing mounts BillingEntryForm scoped to that rental id (fails if the billing add is unwired or scoped to the wrong rental)', () => {
    render(<SpotRentalList vin="V1" />)
    fireEvent.click(screen.getByRole('button', { name: 'spotRentalList.addBilling' }))
    expect(screen.getByTestId('billing-form')).toHaveTextContent('billing:1:new')
  })
})

describe('SpotRentalList — billing disclosure + edit/delete (B5/B6, ≥2-billing fixture)', () => {
  it('the disclosure toggle flips aria-expanded false→true and reveals the expanded billing rows (fails if the toggle is unwired or aria-expanded is missing)', () => {
    render(<SpotRentalList vin="V1" />)
    // billingCount === 2 (>1) ⇒ the expand/collapse toggle renders, collapsed initially.
    const toggle = screen.getByRole('button', { name: 'spotRentalList.viewAllBillings' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByText('spotRentalList.allBillingEntries')).not.toBeInTheDocument()
    fireEvent.click(toggle)
    // Same button node; aria-expanded now true and the expanded panel (its h6 heading) is present.
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('spotRentalList.allBillingEntries')).toBeInTheDocument()
  })

  it('a billing-row Edit mounts BillingEntryForm scoped to the rental id + THAT billing id (fails if billing edit is unwired or passes the wrong billing)', () => {
    render(<SpotRentalList vin="V1" />)
    fireEvent.click(screen.getByRole('button', { name: 'spotRentalList.viewAllBillings' }))
    // Two expanded billings ⇒ two edit buttons; the first row is billing id 90.
    fireEvent.click(screen.getAllByRole('button', { name: 'spotRentalList.editBilling' })[0])
    expect(screen.getByTestId('billing-form')).toHaveTextContent('billing:1:90')
  })

  it('a billing-row Delete with confirm ACCEPTED calls api.delete with the EXACT billing URL (fails if the delete URL shape changes or the confirm gate is dropped)', async () => {
    render(<SpotRentalList vin="V1" />)
    fireEvent.click(screen.getByRole('button', { name: 'spotRentalList.viewAllBillings' }))
    fireEvent.click(screen.getAllByRole('button', { name: 'spotRentalList.deleteBilling' })[0])
    await answerConfirm('confirm', 'spotRentalList.confirmDeleteBilling')
    // The REAL handleDeleteBilling (SpotRentalList.tsx:80-92):
    // api.delete(`/vehicles/${vin}/spot-rentals/${rentalId}/billings/${billingId}`).
    expect(apiDelete).toHaveBeenCalledWith('/vehicles/V1/spot-rentals/1/billings/90')
  })

  it('a billing-row Delete with confirm REJECTED does NOT call api.delete (fails if the handler ignores a false confirm)', async () => {
    render(<SpotRentalList vin="V1" />)
    fireEvent.click(screen.getByRole('button', { name: 'spotRentalList.viewAllBillings' }))
    fireEvent.click(screen.getAllByRole('button', { name: 'spotRentalList.deleteBilling' })[0])
    await answerConfirm('cancel', 'spotRentalList.confirmDeleteBilling')
    expect(apiDelete).not.toHaveBeenCalled()
  })
})
