import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { screen, fireEvent, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ServiceVisit } from '../../types/serviceVisit'
import { METRIC_UNITS } from '../../__tests__/factories'
import { formatDateForDisplay } from '../../utils/dateUtils'
// The list reads its link params from the router, so every render needs one.
import { render, render as renderWithRouter } from '../../__tests__/test-utils'

const useServiceVisitsMock = vi.fn()
const deleteMutate = vi.fn()

vi.mock('../../hooks/queries/useServiceVisits', () => ({
  useServiceVisits: () => useServiceVisitsMock(),
  useDeleteServiceVisit: () => ({ mutate: deleteMutate, isPending: false, variables: undefined }),
  useServiceVisit: () => ({ data: undefined, isError: false }),
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
    // The disclosure button holds only the chevron and takes its name from the
    // visit's title and date through aria-labelledby, so the date, chip, vendor
    // and total stay outside it where a long-press can select them (#179).
    const disclosure = screen.getByRole('button', { name: `Tire rotation ${formatDateForDisplay('2026-03-01')}` })
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

/**
 * The visit row's text can be selected (issue #179). jsdom pins structure and
 * handlers only: nothing readable sits inside a button, the row toggles on a
 * click, and a click that ends a selection doesn't. Whether a long-press
 * actually selects on a phone is the E2E half.
 */
describe('ServiceVisitList: the visit row keeps its text selectable (#179)', () => {
  const vendorVisit = { ...visit, vendor: { id: 3, name: 'Summit Auto' } } as unknown as ServiceVisit

  beforeEach(() => {
    useServiceVisitsMock.mockReturnValue({ data: { visits: [vendorVisit] }, isLoading: false, error: null })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it("the visit's date, odometer, vendor and total are not inside a button", async () => {
    // RED today: the whole header is one <button>, and text inside a button
    // can't be long-pressed on a phone.
    render(<ServiceVisitList {...PROPS} />)
    const readings = [
      screen.getByText(formatDateForDisplay('2026-03-01')),
      await screen.findByText(/80,467/),
      screen.getByText('Summit Auto'),
      screen.getByText('$40.00'),
    ]

    expect(readings.filter((el) => el.closest('button') !== null)).toEqual([])
  })

  it("clicking the row still toggles it; ending a selection doesn't", () => {
    // RED today on the selection half: the button toggles on every click.
    // Found by its state, not its name, so the RED is the toggle and not the
    // query (the name changed with the restructure; the B7 test pins it).
    render(<ServiceVisitList {...PROPS} />)
    const disclosure = screen.getByRole('button', { expanded: false })
    vi.spyOn(window, 'getSelection').mockReturnValue({
      isCollapsed: false,
      toString: () => 'Summit Auto',
    } as unknown as Selection)

    fireEvent.click(screen.getByText('Summit Auto'))
    expect(disclosure).toHaveAttribute('aria-expanded', 'false')

    vi.mocked(window.getSelection).mockRestore()
    fireEvent.click(screen.getByText('Summit Auto'))
    expect(disclosure).toHaveAttribute('aria-expanded', 'true')
    fireEvent.click(screen.getByText(formatDateForDisplay('2026-03-01')))
    expect(disclosure).toHaveAttribute('aria-expanded', 'false')
  })

  it('two visits with the same title get different names', () => {
    // RED with a title-only aria-labelledby: both read "Tire rotation". The
    // date makes them tell apart. Mutant that kills it: drop the date's id
    // from aria-labelledby.
    const later = { ...visit, id: 2, date: '2026-06-15' } as unknown as ServiceVisit
    useServiceVisitsMock.mockReturnValue({ data: { visits: [visit, later] }, isLoading: false, error: null })
    render(<ServiceVisitList {...PROPS} />)

    expect(screen.getAllByRole('button', { expanded: false })).toHaveLength(2)
    expect(screen.getByRole('button', { name: `Tire rotation ${formatDateForDisplay('2026-03-01')}` })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: `Tire rotation ${formatDateForDisplay('2026-06-15')}` })).toBeInTheDocument()
  })

  it("Edit and Delete do their own thing and don't toggle the row", () => {
    // Guard: they were siblings of the disclosure button before, so they
    // never toggled. Now they sit inside the clickable row and the row's
    // cameFromNestedControl check is what keeps them out. Mutant that kills
    // it: drop cameFromNestedControl from the row's onClick.
    render(<ServiceVisitList {...PROPS} />)
    const disclosure = screen.getByRole('button', { expanded: false })

    // Checked after each click: two stray toggles would cancel out.
    fireEvent.click(screen.getByRole('button', { name: 'common:edit' }))
    expect(onEditClick).toHaveBeenCalledTimes(1)
    expect(disclosure).toHaveAttribute('aria-expanded', 'false')

    fireEvent.click(screen.getByRole('button', { name: 'common:delete' }))
    expect(deleteMutate).toHaveBeenCalledTimes(1)
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

describe('ServiceVisitList: a service line shows what it cost and opens its detail', () => {
  // Labor 40.00 + one supply at 9.52. The header's total already includes the
  // parts (the backend's calculated_total_cost), so both read $49.52.
  const partsVisit = {
    ...visit,
    calculated_total_cost: '49.52',
    total_cost: '49.52',
    line_items: [
      {
        id: 11,
        description: 'Oil change',
        cost: '40.00',
        is_inspection: false,
        inspection_result: null,
        inspection_severity: null,
        notes: 'copy me please',
        supply_usages: [
          { id: 5, supply_id: 42, supply_name: 'Motor Oil', quantity: '4.732', cost_snapshot: '9.52', unit_type: 'volume', volume_unit: 'qt_us', created_at: 'x' },
        ],
      },
    ],
  } as unknown as ServiceVisit

  beforeEach(() => {
    useServiceVisitsMock.mockReturnValue({ data: { visits: [partsVisit] }, isLoading: false, error: null })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  // The detail holds a <Link>, so these need the router from test-utils.
  const openVisit = (): void => {
    renderWithRouter(<ServiceVisitList {...PROPS} />)
    fireEvent.click(screen.getByRole('button', { expanded: false }))
  }
  const detailOpen = (): boolean => document.querySelector('[data-testid="drawer-backdrop"]') !== null

  it('the line total is labor plus parts, with the split underneath', () => {
    openVisit()

    expect(screen.getAllByText('$49.52')).toHaveLength(2)
    expect(screen.getByText(/serviceList\.laborCost/)).toBeInTheDocument()
    expect(screen.getByText(/serviceList\.partsCost/)).toBeInTheDocument()
  })

  it("clicking the line opens its detail; ending a selection in it doesn't (#179)", () => {
    openVisit()
    vi.spyOn(window, 'getSelection').mockReturnValue({
      isCollapsed: false,
      toString: () => 'copy me',
    } as unknown as Selection)

    fireEvent.click(screen.getByText('copy me please'))
    expect(detailOpen()).toBe(false)

    vi.mocked(window.getSelection).mockRestore()
    fireEvent.click(screen.getByText('copy me please'))
    expect(detailOpen()).toBe(true)
  })

  it('the cost breakdown lists the parts, so its rows add up to the total', () => {
    // Subtotal is labor only; without a parts row, $40 + $3 tax reads as $52.52.
    useServiceVisitsMock.mockReturnValue({
      data: { visits: [{ ...partsVisit, tax_amount: '3.00', parts_supplies_cost: '9.52', calculated_total_cost: '52.52' }] },
      isLoading: false,
      error: null,
    })
    openVisit()

    const partsRow = screen.getByText('serviceList.detail.parts:').parentElement
    expect(partsRow).toHaveTextContent('$9.52')
  })

  it('the line keeps a named button for keyboard users', async () => {
    const user = userEvent.setup()
    openVisit()

    screen.getByRole('button', { name: 'serviceList.detail.viewDetails' }).focus()
    await user.keyboard('{Enter}')
    expect(detailOpen()).toBe(true)
  })
})

describe('ServiceVisitList: reference numbers', () => {
  it('shows each stored ref beside the claim line and skips the empty ones', async () => {
    const refsVisit = {
      ...visit,
      insurance_claim_number: 'CLM-9',
      invoice_number: '4CCS403925',
      po_number: null,
      work_order_number: 'WO-12',
    } as unknown as ServiceVisit
    useServiceVisitsMock.mockReturnValue({ data: { visits: [refsVisit] }, isLoading: false, error: null })
    render(<ServiceVisitList {...PROPS} />)

    fireEvent.click(screen.getByRole('button', { name: `Tire rotation ${formatDateForDisplay('2026-03-01')}` }))

    await waitFor(() => expect(screen.getByText('4CCS403925')).toBeInTheDocument())
    expect(screen.getByText('4CCS403925').parentElement).toHaveTextContent('serviceList.invoice: 4CCS403925')
    expect(screen.getByText('WO-12').parentElement).toHaveTextContent('serviceList.workOrder: WO-12')
    expect(screen.getByText('CLM-9').parentElement).toHaveTextContent('serviceList.insuranceClaim: CLM-9')
    expect(screen.queryByText(/serviceList\.po:/)).toBeNull()
  })
})
