import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ServiceVisit } from '../../types/serviceVisit'
import { METRIC_UNITS } from '../../__tests__/factories'

const useServiceVisitsMock = vi.fn()
const deleteMutate = vi.fn()

vi.mock('../../hooks/queries/useServiceVisits', () => ({
  useServiceVisits: () => useServiceVisitsMock(),
  useDeleteServiceVisit: () => ({ mutate: deleteMutate, isPending: false, variables: undefined }),
}))
// Hoisted + mutable (kept "mock"-prefixed per Vitest's factory-hoisting rule) so the
// Task 14 usage-tracking suite below can vary the /vehicles/{vin} response per test;
// every other test in this file leaves it at the attachments-only default.
const apiGetMock = vi.fn().mockResolvedValue({ data: { attachments: [] } })
vi.mock('../../services/api', () => ({ default: { get: (...args: unknown[]) => apiGetMock(...args) } }))
vi.mock('../../hooks/useUnitPreference', () => ({
  useUnitPreference: () => ({
    system: 'metric',
    showBoth: false,
    gallonStandard: 'us',
    // The RESOLVED set, not just the collapsed system: this component reads
    // its distance through `useUnitFormat()`, which closes over `units`.
    units: METRIC_UNITS,
  }),
}))
vi.mock('../../hooks/useCurrencyPreference', () => ({ useCurrencyPreference: () => ({ currencyCode: 'USD', locale: 'en-US' }) }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import ServiceVisitList from '../ServiceVisitList'

// NOTE: formatCurrency is imported from utils/formatUtils (NOT the currency hook),
// so the REAL formatter runs — formatCurrency(40) → "$40.00".
const visit = {
  id: 1,
  vin: 'V1',
  date: '2026-03-01',
  service_category: 'Maintenance',
  notes: 'rotated tires',
  odometer_km: '80467',
  calculated_total_cost: '40.00',
  total_cost: '40.00',
  subtotal: '40.00',
  tax_amount: null,
  shop_supplies: null,
  misc_fees: null,
  vendor: null,
  line_items: [
    { id: 11, description: 'Tire rotation', cost: '40.00', is_inspection: false, inspection_result: null, inspection_severity: null, notes: null },
  ],
} as unknown as ServiceVisit

const onAddClick = vi.fn()
const onEditClick = vi.fn()
const PROPS = { vin: 'V1', onAddClick, onEditClick }

beforeEach(() => {
  vi.clearAllMocks()
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  useServiceVisitsMock.mockReturnValue({ data: { visits: [visit] }, isLoading: false, error: null })
})

describe('ServiceVisitList — rendering + category chip', () => {
  it('renders the category label and the visit total (fails if the Chip label or the total cell is dropped)', () => {
    render(<ServiceVisitList {...PROPS} />)
    // The category label is ALWAYS shown (colour is never the sole channel, SDQ-B2).
    expect(screen.getByText('Maintenance')).toBeInTheDocument()
    // real formatCurrency('40.00') → "$40.00" (total > 0 branch).
    expect(screen.getByText('$40.00')).toBeInTheDocument()
  })
})

describe('ServiceVisitList — row actions fire the real handlers', () => {
  it('clicking row Edit calls onEditClick with THE WHOLE visit (fails if edit is unwired, passes the wrong row, or a truncated object)', () => {
    render(<ServiceVisitList {...PROPS} />)
    fireEvent.click(screen.getByRole('button', { name: 'common:edit' }))
    expect(onEditClick).toHaveBeenCalledWith(visit)
  })

  it('clicking row Delete (confirm accepted) calls the delete mutation with the visit id (fails if delete is unwired or the confirm gate is dropped)', () => {
    render(<ServiceVisitList {...PROPS} />)
    fireEvent.click(screen.getByRole('button', { name: 'common:delete' }))
    expect(window.confirm).toHaveBeenCalled()
    expect(deleteMutate).toHaveBeenCalledWith(1, expect.anything())
  })

  it('the row Edit/Delete expose a real aria-label (IconButton), not a bare title (fails if IconButton regresses to a title-only <button>)', () => {
    render(<ServiceVisitList {...PROPS} />)
    // getByRole name resolves via the title→accessible-name fallback even on the
    // OLD title-only buttons, so assert the aria-label ATTRIBUTE itself — that is
    // what distinguishes the IconButton migration and is RED pre-restyle.
    expect(screen.getByRole('button', { name: 'common:edit' })).toHaveAttribute('aria-label', 'common:edit')
    expect(screen.getByRole('button', { name: 'common:delete' })).toHaveAttribute('aria-label', 'common:delete')
  })
})

describe('ServiceVisitList — keyboard-operable disclosure (B7)', () => {
  it('the header disclosure is a focusable <button> whose aria-expanded toggles on Enter and Space, revealing/hiding the notes (fails if it regresses to a non-focusable div or the toggle is unwired)', async () => {
    const user = userEvent.setup()
    render(<ServiceVisitList {...PROPS} />)
    // The disclosure button's accessible name is the concatenation of its header
    // text (date, category, summary, mileage, total); 'Maintenance' is a stable
    // substring. The edit/delete IconButtons are SIBLINGS outside it, so this
    // regex matches ONLY the disclosure control.
    const disclosure = screen.getByRole('button', { name: /Maintenance/ })
    expect(disclosure).toHaveAttribute('aria-expanded', 'false')
    // Notes live only in the expanded panel.
    expect(screen.queryByText('rotated tires')).not.toBeInTheDocument()
    disclosure.focus()
    expect(disclosure).toHaveFocus()
    await user.keyboard('{Enter}')
    expect(disclosure).toHaveAttribute('aria-expanded', 'true')
    await waitFor(() => expect(screen.getByText('rotated tires')).toBeInTheDocument())
    await user.keyboard(' ') // Space activates a focused button → collapses
    expect(disclosure).toHaveAttribute('aria-expanded', 'false')
  })
})

describe('ServiceVisitList — search filters, empty state CTA', () => {
  it('a non-matching search shows the no-match empty state and hides the visit (fails if search filtering breaks)', () => {
    render(<ServiceVisitList {...PROPS} />)
    fireEvent.change(screen.getByRole('searchbox', { name: 'serviceList.searchPlaceholder' }), { target: { value: 'zzz-no-match' } })
    expect(screen.getByText('serviceList.noMatchingVisits')).toBeInTheDocument()
    expect(screen.queryByText('Maintenance')).not.toBeInTheDocument()
  })

  it('with zero visits, the empty-state CTA fires onAddClick (fails if the CTA is unwired or the title text changes)', () => {
    useServiceVisitsMock.mockReturnValue({ data: { visits: [] }, isLoading: false, error: null })
    render(<ServiceVisitList {...PROPS} />)
    expect(screen.getByText('serviceList.noRecords')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'serviceList.logFirstVisit' }))
    expect(onAddClick).toHaveBeenCalled()
  })
})

describe('ServiceVisitList — engine-hours usage tracking (Task 14)', () => {
  // A visit carrying BOTH readings — distinct decimals from each other so a
  // regex match against one can't accidentally hit the other, and so the
  // gating tests genuinely discriminate tracksDistance/tracksHours (not just
  // a null-guard on an absent field).
  const bothReadingsVisit = { ...visit, id: 5, odometer_km: '80467', engine_hours: '812.4' } as unknown as ServiceVisit

  beforeEach(() => {
    useServiceVisitsMock.mockReturnValue({ data: { visits: [bothReadingsVisit] }, isLoading: false, error: null })
  })

  it('shows the engine-hours reading (and hides odometer) for an hours-tracking vehicle', async () => {
    apiGetMock.mockResolvedValueOnce({ data: { usage_unit: 'hours', secondary_usage_enabled: false } })
    render(<ServiceVisitList {...PROPS} />)
    await waitFor(() => expect(apiGetMock).toHaveBeenCalled())

    expect(await screen.findByText(/812\.4/)).toBeInTheDocument()
    expect(screen.queryByText(/80,467/)).not.toBeInTheDocument()
  })

  it('shows the odometer reading (and hides engine-hours) for a distance-tracking vehicle', async () => {
    apiGetMock.mockResolvedValueOnce({ data: { usage_unit: 'distance', secondary_usage_enabled: false } })
    render(<ServiceVisitList {...PROPS} />)
    await waitFor(() => expect(apiGetMock).toHaveBeenCalled())

    expect(await screen.findByText(/80,467/)).toBeInTheDocument()
    expect(screen.queryByText(/812\.4/)).not.toBeInTheDocument()
  })

  it('shows BOTH odometer and engine-hours readings for a dual-tracking vehicle', async () => {
    apiGetMock.mockResolvedValueOnce({ data: { usage_unit: 'distance', secondary_usage_enabled: true } })
    render(<ServiceVisitList {...PROPS} />)
    await waitFor(() => expect(apiGetMock).toHaveBeenCalled())

    expect(await screen.findByText(/812\.4/)).toBeInTheDocument()
    expect(screen.getByText(/80,467/)).toBeInTheDocument()
  })

  it('keeps the odometer reading and shows no engine-hours for a pure-distance vehicle (list unchanged)', async () => {
    // apiGetMock default (module scope) returns attachments-only — no usage_unit,
    // defaults to distance, matching every pre-existing test in this file.
    render(<ServiceVisitList {...PROPS} />)
    await waitFor(() => expect(apiGetMock).toHaveBeenCalled())

    expect(await screen.findByText(/80,467/)).toBeInTheDocument()
    expect(screen.queryByText(/812\.4/)).not.toBeInTheDocument()
  })
})
