import { describe, it, expect, vi, beforeEach } from 'vitest'
// TaxRecordList calls useQueryClient() (TaxRecordList.tsx:18), so it MUST render inside the QueryClient+Router
// providers test-utils supplies (setup.ts does NOT mock @tanstack/react-query; bare @testing-library/react
// render would throw "No QueryClient set"). test-utils re-exports screen/within/fireEvent — nothing else changes.
import { render, screen, within, fireEvent } from '../../__tests__/test-utils'
import { formatCurrency } from '../../utils/formatUtils'
import { formatDateForDisplay } from '../../utils/dateUtils'
import type { TaxRecord } from '../../types/tax'

const useTaxRecordsMock = vi.fn()
const deleteMutate = vi.fn()
vi.mock('../../hooks/queries/useTaxRecords', () => ({
  useTaxRecords: () => useTaxRecordsMock(),
  useDeleteTaxRecord: () => ({ mutate: deleteMutate, isPending: false, variables: undefined }),
}))
vi.mock('../../hooks/useCurrencyPreference', () => ({ useCurrencyPreference: () => ({ currencyCode: 'USD', locale: 'en-US', formatCurrency: vi.fn() }) }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
// The list mounts TaxRecordForm itself; stub it so the internal Add/Edit routing is assertable
// (it echoes whether it is creating or editing which record) without rendering the real form.
vi.mock('../TaxRecordForm', () => ({
  default: ({ record }: { record?: { id: number } }) => <div data-testid="tax-form">{record ? `editing:${record.id}` : 'creating'}</div>,
}))

import TaxRecordList from '../TaxRecordList'

const recA = { id: 1, date: '2026-03-01', tax_type: 'registration', amount: '85.50', renewal_date: '2027-03-01', notes: 'annual' } as unknown as TaxRecord
const recB = { id: 2, date: '2026-04-01', tax_type: 'inspection', amount: '40.00', renewal_date: null, notes: '' } as unknown as TaxRecord
const money = (v: number | string) => formatCurrency(v, { currencyCode: 'USD', locale: 'en-US' })
// The caption-scoped helper (RED until the DataTable adds <caption>) — RESERVED for the DataTable-SPECIFIC
// column/caption assertions (RED→GREEN across the restyle).
const table = () => screen.getByRole('table', { name: 'taxList.tableCaption' })
// The UNNAMED single-table helper — the current raw <table> AND the post-restyle DataTable both resolve here
// (there is exactly ONE table either way). Used by the pre-existing-behaviour ACTION tests so they run to
// their assertion pre-restyle (GREEN + sabotage-proven) instead of failing on a caption that does not exist
// yet (R2-M1).
const anyTable = () => screen.getByRole('table')

beforeEach(() => {
  vi.clearAllMocks()
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  useTaxRecordsMock.mockReturnValue({ data: { records: [recA, recB] }, isLoading: false, error: null })
})

describe('TaxRecordList — DataTable cells scoped to the named table', () => {
  it('renders BOTH row amounts INSIDE the named DataTable, and the header total OUTSIDE it (fails if the DataTable/caption is dropped, a row amount vanishes, or the total leaks into the table)', () => {
    render(<TaxRecordList vin="V1" />)
    // Row cells (85.50, 40.00) live inside the table; the header total (125.50) does not.
    expect(within(table()).getByText(money('85.50'))).toBeInTheDocument()
    expect(within(table()).getByText(money('40.00'))).toBeInTheDocument()
    expect(within(table()).queryByText(money(125.5))).not.toBeInTheDocument()
    // The header total renders somewhere on the page (outside the table).
    expect(screen.getByText(money(125.5))).toBeInTheDocument()
  })

  it('renders the tax type inside the table row (fails if the type column is dropped)', () => {
    render(<TaxRecordList vin="V1" />)
    expect(within(table()).getByText('forms:taxTypes.registration')).toBeInTheDocument()
  })

  it('renders EVERY column render-transform inside the named table — date, both amounts, renewal date + its fallback, notes + its fallback, and both types (M2 — fails if any column render is dropped)', () => {
    render(<TaxRecordList vin="V1" />)
    const rowA = within(table()).getByText('forms:taxTypes.registration').closest('tr') as HTMLElement
    const rowB = within(table()).getByText('forms:taxTypes.inspection').closest('tr') as HTMLElement
    // Row A — every field populated. Real formatter output (no dateLocale arg — the column render passes none).
    expect(within(rowA).getByText(formatDateForDisplay('2026-03-01'))).toBeInTheDocument()  // datePaid
    expect(within(rowA).getByText(money('85.50'))).toBeInTheDocument()                       // amount
    expect(within(rowA).getByText(formatDateForDisplay('2027-03-01'))).toBeInTheDocument()   // renewalDate
    expect(within(rowA).getByText('annual')).toBeInTheDocument()                             // notes
    // Row B — null renewal_date + empty notes BOTH fall back to '-'.
    expect(within(rowB).getByText(formatDateForDisplay('2026-04-01'))).toBeInTheDocument()   // datePaid
    expect(within(rowB).getByText(money('40.00'))).toBeInTheDocument()                       // amount
    expect(within(rowB).getAllByText('-')).toHaveLength(2)                                   // renewal + notes fallbacks
  })

  it('exposes EXACTLY ONE table role — the DataTable — so no legacy raw <table> lingers (B6 — fails if the old raw table is left in place beside the DataTable)', () => {
    render(<TaxRecordList vin="V1" />)
    expect(screen.getAllByRole('table')).toHaveLength(1)
  })
})

describe('TaxRecordList — row actions + add', () => {
  it('clicking a row Edit opens the form editing THAT record (fails if edit is unwired or opens the wrong/blank record)', () => {
    render(<TaxRecordList vin="V1" />)
    const firstRow = within(anyTable()).getByText('forms:taxTypes.registration').closest('tr') as HTMLElement
    fireEvent.click(within(firstRow).getByRole('button', { name: 'common:edit' }))
    expect(screen.getByTestId('tax-form')).toHaveTextContent('editing:1')
  })

  it('clicking a row Delete (confirm accepted) calls the delete mutation with the record id (fails if delete is unwired or the confirm gate is dropped)', () => {
    render(<TaxRecordList vin="V1" />)
    const firstRow = within(anyTable()).getByText('forms:taxTypes.registration').closest('tr') as HTMLElement
    fireEvent.click(within(firstRow).getByRole('button', { name: 'common:delete' }))
    expect(window.confirm).toHaveBeenCalled()
    expect(deleteMutate).toHaveBeenCalledWith(1, expect.anything())
  })

  it('clicking a row Delete with confirm REJECTED does NOT call the delete mutation (B4 — fails if the handler ignores a false confirm and deletes anyway)', () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    render(<TaxRecordList vin="V1" />)
    const firstRow = within(anyTable()).getByText('forms:taxTypes.registration').closest('tr') as HTMLElement
    fireEvent.click(within(firstRow).getByRole('button', { name: 'common:delete' }))
    expect(window.confirm).toHaveBeenCalled()
    expect(deleteMutate).not.toHaveBeenCalled()
  })

  it('the row Edit/Delete expose a real aria-label via IconButton (fails if IconButton regresses to a title-only <button>)', () => {
    render(<TaxRecordList vin="V1" />)
    const firstRow = within(anyTable()).getByText('forms:taxTypes.registration').closest('tr') as HTMLElement
    expect(within(firstRow).getByRole('button', { name: 'common:edit' })).toHaveAttribute('aria-label', 'common:edit')
    expect(within(firstRow).getByRole('button', { name: 'common:delete' })).toHaveAttribute('aria-label', 'common:delete')
  })

  it('the header Add opens the form in create mode (fails if Add is unwired)', () => {
    render(<TaxRecordList vin="V1" />)
    fireEvent.click(screen.getByRole('button', { name: 'taxList.addRecord' }))
    expect(screen.getByTestId('tax-form')).toHaveTextContent('creating')
  })
})

describe('TaxRecordList — empty state', () => {
  it('with zero records, the empty-state CTA opens the form in create mode (fails if the CTA is unwired or the title text changes)', () => {
    useTaxRecordsMock.mockReturnValue({ data: { records: [] }, isLoading: false, error: null })
    render(<TaxRecordList vin="V1" />)
    expect(screen.getByText('taxList.noRecords')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'taxList.addFirstRecord' }))
    expect(screen.getByTestId('tax-form')).toHaveTextContent('creating')
  })
})
