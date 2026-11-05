import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import type { ReactElement } from 'react'
import type { ServiceVisit } from '../../types/serviceVisit'
import { METRIC_UNITS } from '../../__tests__/factories'

// The English bundle, so chip text reads as a user sees it.
vi.mock('react-i18next', async () => (await import('@/__tests__/i18nEn')).reactI18nextEn())

const useServiceVisitsMock = vi.fn()
const useServiceVisitMock = vi.fn()
vi.mock('../../hooks/queries/useServiceVisits', () => ({
  useServiceVisits: () => useServiceVisitsMock(),
  useServiceVisit: (...args: unknown[]) => useServiceVisitMock(...args),
  useDeleteServiceVisit: () => ({ mutate: vi.fn(), isPending: false, variables: undefined }),
}))
vi.mock('../../services/api', () => ({ default: { get: vi.fn().mockResolvedValue({ data: { attachments: [] } }) } }))
vi.mock('../../hooks/useUnitPreference', () => ({
  useUnitPreference: () => ({ system: 'metric', showBoth: false, gallonStandard: 'us', units: METRIC_UNITS }),
}))
vi.mock('../../hooks/useCurrencyPreference', () => ({ useCurrencyPreference: () => ({ currencyCode: 'USD', locale: 'en-US' }) }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import ServiceVisitList from '../ServiceVisitList'

const item = (over: Record<string, unknown>): Record<string, unknown> => ({
  description: 'Line',
  cost: null,
  is_inspection: false,
  inspection_result: null,
  inspection_severity: null,
  notes: null,
  is_recall: false,
  recall_id: null,
  recall_summary: null,
  is_warranty: false,
  warranty_id: null,
  warranty_summary: null,
  supply_usages: [],
  ...over,
})

const visit = {
  id: 1,
  vin: 'V1',
  date: '2026-11-03',
  service_category: 'Maintenance',
  notes: null,
  odometer_km: null,
  calculated_total_cost: '0.00',
  total_cost: '0.00',
  subtotal: '0.00',
  tax_amount: null,
  shop_supplies: null,
  misc_fees: null,
  vendor: { id: 3, name: 'EAG' },
  insurance_claim_number: 'CLM-9',
  invoice_number: null,
  po_number: null,
  work_order_number: null,
  line_items: [
    item({
      id: 11,
      description: 'Air bag inflator',
      is_recall: true,
      recall_id: 41,
      recall_summary: { id: 41, campaign: '26V059000', component: 'Air Bags' },
      is_warranty: true,
      warranty_id: 9,
      warranty_summary: { id: 9, warranty_type: 'Powertrain', provider: 'Toyota' },
    }),
    // A recall done with no recall record in MyGarage (D8).
    item({ id: 12, description: 'Seat belt retractor', is_recall: true }),
    item({ id: 13, description: 'Wipers' }),
  ],
} as unknown as ServiceVisit

// Older than the list's first page: only the single-visit fetch has it.
const oldVisit = {
  ...visit,
  id: 500,
  date: '2019-04-02',
  insurance_claim_number: null,
  line_items: [item({ id: 9001, description: 'Water pump', is_warranty: true, warranty_id: 9 })],
} as unknown as ServiceVisit

function Where(): ReactElement {
  const location = useLocation()
  return <div data-testid="where">{location.pathname + location.search}</div>
}

function renderAt(url: string): void {
  render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route
          path="/vehicles/:vin"
          element={
            <>
              <ServiceVisitList vin="V1" onAddClick={vi.fn()} onEditClick={vi.fn()} />
              <Where />
            </>
          }
        />
      </Routes>
    </MemoryRouter>,
  )
}

const expand = (): void => {
  fireEvent.click(screen.getByRole('button', { expanded: false }))
}
const openButton = (description: string): HTMLElement =>
  screen.getByRole('button', { name: `View details for ${description}` })
// The card around that hidden button, where the chips sit.
const row = (description: string): HTMLElement =>
  openButton(description).parentElement?.parentElement as HTMLElement

beforeEach(() => {
  vi.clearAllMocks()
  useServiceVisitsMock.mockReturnValue({ data: { visits: [visit] }, isLoading: false, error: null })
  useServiceVisitMock.mockReturnValue({ data: undefined, isError: false })
})

describe('ServiceVisitList: recall and warranty items', () => {
  it('chips a linked recall by campaign, an unlinked one plainly, and a warranty item', () => {
    renderAt('/vehicles/V1?tab=service')
    expand()

    expect(within(row('Air bag inflator')).getByText('Recall 26V059000')).toBeInTheDocument()
    expect(within(row('Air bag inflator')).getByText('Warranty')).toBeInTheDocument()
    expect(within(row('Seat belt retractor')).getByText('Recall')).toBeInTheDocument()
    expect(within(row('Seat belt retractor')).queryByText('Warranty')).not.toBeInTheDocument()
    expect(within(row('Wipers')).queryByText(/Recall|Warranty/)).not.toBeInTheDocument()
  })

  it('labels the claim "Insurance Claim #" like the other refs', () => {
    renderAt('/vehicles/V1?tab=service')
    expand()

    expect(screen.getByText('CLM-9').parentElement).toHaveTextContent('Insurance Claim #: CLM-9')
  })

  it('the service detail shows the same chips', () => {
    renderAt('/vehicles/V1?tab=service')
    expand()
    fireEvent.click(openButton('Air bag inflator'))

    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText('Recall 26V059000')).toBeInTheDocument()
    expect(within(dialog).getByText('Warranty')).toBeInTheDocument()
  })
})

describe('ServiceVisitList: opening a service line from a link', () => {
  it('opens a visit that is not in the first page, then drops the link params on close', async () => {
    useServiceVisitMock.mockImplementation((_vin: string, id: number | null) =>
      id === 500 ? { data: oldVisit, isError: false } : { data: undefined, isError: false },
    )
    renderAt('/vehicles/V1?tab=service&visit=500&item=9001')

    expect(useServiceVisitMock).toHaveBeenCalledWith('V1', 500)
    const dialog = await screen.findByRole('dialog', { name: 'Water pump' })
    expect(within(dialog).getByText('Warranty')).toBeInTheDocument()

    fireEvent.click(within(dialog).getAllByRole('button', { name: 'Close' })[0])

    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent(/^\/vehicles\/V1\?tab=service$/))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('a link to an item the visit no longer has opens nothing and drops the params', async () => {
    useServiceVisitMock.mockImplementation((_vin: string, id: number | null) =>
      id === 500 ? { data: oldVisit, isError: false } : { data: undefined, isError: false },
    )
    renderAt('/vehicles/V1?tab=service&visit=500&item=4')

    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent(/^\/vehicles\/V1\?tab=service$/))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})
