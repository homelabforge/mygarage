import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within, fireEvent } from '../../__tests__/test-utils'
import { formatCurrency } from '../../utils/formatUtils'
import { formatDateForDisplay } from '../../utils/dateUtils'
import type { FinancingRecord } from '../../types/financing'

const useFinancingRecordsMock = vi.fn()
const deleteMutate = vi.fn()
vi.mock('../../hooks/queries/useFinancingRecords', () => ({
  useFinancingRecords: () => useFinancingRecordsMock(),
  useDeleteFinancingRecord: () => ({ mutate: deleteMutate, isPending: false, variables: undefined }),
}))
vi.mock('../../hooks/useCurrencyPreference', () => ({ useCurrencyPreference: () => ({ currencyCode: 'USD', locale: 'en-US', formatCurrency: vi.fn() }) }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
// Stub the form so the list's Add/Edit routing can be asserted.
vi.mock('../FinancingRecordForm', () => ({
  default: ({ record }: { record?: { id: number } }) => <div data-testid="financing-form">{record ? `editing:${record.id}` : 'creating'}</div>,
}))

import FinancingRecordList from '../FinancingRecordList'
import { answerConfirm } from '../../__tests__/confirmHelpers'

const recA = {
  id: 1, date: '2026-03-01', category: 'lease_payment', amount: '450.00', vendor_id: 5, notes: 'monthly',
  lender: { id: 5, name: 'Toyota Financial', city: null, state: null },
} as unknown as FinancingRecord
const recB = { id: 2, date: '2026-04-01', category: 'upfront_fee', amount: '1200.00', vendor_id: null, notes: '', lender: null } as unknown as FinancingRecord
const money = (v: number | string) => formatCurrency(v, { currencyCode: 'USD', locale: 'en-US' })
const table = () => screen.getByRole('table', { name: 'financingList.tableCaption' })

beforeEach(() => {
  vi.clearAllMocks()
  useFinancingRecordsMock.mockReturnValue({ data: { financing_records: [recA, recB] }, isLoading: false, error: null })
})

describe('FinancingRecordList — DataTable cells scoped to the named table', () => {
  it('renders BOTH row amounts INSIDE the named DataTable, and the header total OUTSIDE it (fails if the DataTable/caption is dropped, a row amount vanishes, or the total leaks into the table)', () => {
    render(<FinancingRecordList vin="V1" />)
    expect(within(table()).getByText(money('450.00'))).toBeInTheDocument()
    expect(within(table()).getByText(money('1200.00'))).toBeInTheDocument()
    expect(within(table()).queryByText(money(1650))).not.toBeInTheDocument()
    expect(screen.getByText(money(1650))).toBeInTheDocument()
  })

  it('renders the category label inside the table row (fails if the category column is dropped)', () => {
    render(<FinancingRecordList vin="V1" />)
    expect(within(table()).getByText('forms:financingCategories.leasePayment')).toBeInTheDocument()
    expect(within(table()).getByText('forms:financingCategories.upfrontFee')).toBeInTheDocument()
  })

  it('renders EVERY column render-transform inside the named table — date, amount, notes + its fallback (fails if any column render is dropped)', () => {
    render(<FinancingRecordList vin="V1" />)
    const rowA = within(table()).getByText('forms:financingCategories.leasePayment').closest('tr') as HTMLElement
    const rowB = within(table()).getByText('forms:financingCategories.upfrontFee').closest('tr') as HTMLElement
    expect(within(rowA).getByText(formatDateForDisplay('2026-03-01'))).toBeInTheDocument()
    expect(within(rowA).getByText(money('450.00'))).toBeInTheDocument()
    expect(within(rowA).getByText('monthly')).toBeInTheDocument()
    expect(within(rowB).getByText(formatDateForDisplay('2026-04-01'))).toBeInTheDocument()
    expect(within(rowB).getByText(money('1200.00'))).toBeInTheDocument()
    expect(within(rowB).getAllByText('-')).toHaveLength(2)
  })

  it('exposes EXACTLY ONE table role — the DataTable — so no legacy raw <table> lingers', () => {
    render(<FinancingRecordList vin="V1" />)
    expect(screen.getAllByRole('table')).toHaveLength(1)
  })
})

describe('FinancingRecordList — lender column', () => {
  it('shows "Lender" as the column header, not "Vendor" (fails if the relabel regresses)', () => {
    render(<FinancingRecordList vin="V1" />)
    expect(within(table()).getByText('financingList.lender')).toBeInTheDocument()
  })

  it('renders the lender name straight from the record (fails if the column stops reading r.lender)', () => {
    render(<FinancingRecordList vin="V1" />)
    const rowA = within(table()).getByText('forms:financingCategories.leasePayment').closest('tr') as HTMLElement
    expect(within(rowA).getByText('Toyota Financial')).toBeInTheDocument()
  })

  it('renders "-" for a record with no lender (fails if the empty-lender fallback regresses)', () => {
    render(<FinancingRecordList vin="V1" />)
    const rowB = within(table()).getByText('forms:financingCategories.upfrontFee').closest('tr') as HTMLElement
    expect(within(rowB).getAllByText('-').length).toBeGreaterThan(0)
  })
})

describe('FinancingRecordList — row actions + add', () => {
  it('clicking a row Edit opens the form editing THAT record (fails if edit is unwired or opens the wrong/blank record)', () => {
    render(<FinancingRecordList vin="V1" />)
    const firstRow = within(table()).getByText('forms:financingCategories.leasePayment').closest('tr') as HTMLElement
    fireEvent.click(within(firstRow).getByRole('button', { name: 'common:edit' }))
    expect(screen.getByTestId('financing-form')).toHaveTextContent('editing:1')
  })

  it('clicking a row Delete (confirm accepted) calls the delete mutation with the record id (fails if delete is unwired or the confirm gate is dropped)', async () => {
    render(<FinancingRecordList vin="V1" />)
    const firstRow = within(table()).getByText('forms:financingCategories.leasePayment').closest('tr') as HTMLElement
    fireEvent.click(within(firstRow).getByRole('button', { name: 'common:delete' }))
    await answerConfirm('confirm', 'financingList.confirmDelete')
    expect(deleteMutate).toHaveBeenCalledWith(1, expect.anything())
  })

  it('clicking a row Delete with confirm REJECTED does NOT call the delete mutation (fails if the handler ignores a false confirm and deletes anyway)', async () => {
    render(<FinancingRecordList vin="V1" />)
    const firstRow = within(table()).getByText('forms:financingCategories.leasePayment').closest('tr') as HTMLElement
    fireEvent.click(within(firstRow).getByRole('button', { name: 'common:delete' }))
    await answerConfirm('cancel', 'financingList.confirmDelete')
    expect(deleteMutate).not.toHaveBeenCalled()
  })

  it('the row Edit/Delete expose a real aria-label via IconButton (fails if IconButton regresses to a title-only <button>)', () => {
    render(<FinancingRecordList vin="V1" />)
    const firstRow = within(table()).getByText('forms:financingCategories.leasePayment').closest('tr') as HTMLElement
    expect(within(firstRow).getByRole('button', { name: 'common:edit' })).toHaveAttribute('aria-label', 'common:edit')
    expect(within(firstRow).getByRole('button', { name: 'common:delete' })).toHaveAttribute('aria-label', 'common:delete')
  })

  it('the header Add opens the form in create mode (fails if Add is unwired)', () => {
    render(<FinancingRecordList vin="V1" />)
    fireEvent.click(screen.getByRole('button', { name: 'financingList.addRecord' }))
    expect(screen.getByTestId('financing-form')).toHaveTextContent('creating')
  })
})

describe('FinancingRecordList — empty state', () => {
  it('with zero records, the empty-state CTA opens the form in create mode (fails if the CTA is unwired or the title text changes)', () => {
    useFinancingRecordsMock.mockReturnValue({ data: { financing_records: [] }, isLoading: false, error: null })
    render(<FinancingRecordList vin="V1" />)
    expect(screen.getByText('financingList.noRecords')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'financingList.addFirstRecord' }))
    expect(screen.getByTestId('financing-form')).toHaveTextContent('creating')
  })
})
