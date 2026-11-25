import { describe, it, expect, vi, beforeEach } from 'vitest'
// TollTransactionList calls useQueryClient() (TollTransactionList.tsx:22), so it MUST render inside the
// QueryClient+Router providers that test-utils supplies (setup.ts does NOT mock @tanstack/react-query, and
// bare @testing-library/react render would throw "No QueryClient set"). test-utils re-exports screen/within/
// fireEvent, so nothing else changes. (T6 already uses test-utils for the same reason.)
import { render, screen, within, fireEvent } from '../../__tests__/test-utils'
import { formatCurrency } from '../../utils/formatUtils'
import { formatDateForDisplay } from '../../utils/dateUtils'
import type { TollTransaction } from '../../types/toll'

const useTollTransactionsMock = vi.fn()
const useTollTagsMock = vi.fn()
const useTollTransactionSummaryMock = vi.fn()
const deleteMutate = vi.fn()
vi.mock('../../hooks/queries/useTollRecords', () => ({
  useTollTransactions: () => useTollTransactionsMock(),
  useTollTags: () => useTollTagsMock(),
  useTollTransactionSummary: () => useTollTransactionSummaryMock(),
  useDeleteTollTransaction: () => ({ mutate: deleteMutate, isPending: false, variables: undefined }),
}))
vi.mock('../../hooks/useCurrencyPreference', () => ({ useCurrencyPreference: () => ({ currencyCode: 'USD', locale: 'en-US', formatCurrency: vi.fn() }) }))
vi.mock('../../hooks/useDateLocale', () => ({ useDateLocale: () => undefined }))
vi.mock('../../services/api', () => ({ default: { get: vi.fn() } }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import TollTransactionList from '../TollTransactionList'
import { answerConfirm } from '../../__tests__/confirmHelpers'

const txn = { id: 1, date: '2026-02-10', amount: 3.75, location: 'Beltway Plaza', toll_tag_id: null, notes: 'trip' } as unknown as TollTransaction
const summary = {
  total_transactions: 2,
  total_amount: '10.50',
  monthly_totals: [{ month: '2026-02', count: 1, amount: 7.25 }],
}
const onAddClick = vi.fn()
const onEditClick = vi.fn()
const PROPS = { vin: 'V1', onAddClick, onEditClick }
const money = (v: number | string) => formatCurrency(v, { currencyCode: 'USD', locale: 'en-US' })
const monthlyTable = () => screen.getByRole('table', { name: 'tollList.monthlyBreakdownCaption' })

beforeEach(() => {
  vi.clearAllMocks()
  useTollTransactionsMock.mockReturnValue({ data: { transactions: [txn] }, isLoading: false, error: null })
  useTollTagsMock.mockReturnValue({ data: { toll_tags: [] }, isLoading: false })
  useTollTransactionSummaryMock.mockReturnValue({ data: summary })
})

describe('TollTransactionList — summary tiles + transaction cards', () => {
  it('renders ALL THREE summary tiles (label + value) each scoped to its OWN card (M1 — fails if a tile is dropped or unformatted)', () => {
    render(<TollTransactionList {...PROPS} />)
    // Each tile's label <p> and value <Mono> are siblings inside the tile's inner <div>; scope the value
    // assertion to that div so a value can only satisfy its OWN tile. These tiles exist pre-restyle (bespoke
    // <div>s today) → GREEN + sabotage-proven; queried DIRECTLY, never through monthlyTable() (R2-M1 — the
    // non-leak check lives in the DataTable describe block below, correctly RED→GREEN).
    const tile = (label: string) => screen.getByText(label).closest('div') as HTMLElement
    expect(within(tile('tollList.totalTransactions')).getByText('2')).toBeInTheDocument()             // count (not currency)
    expect(within(tile('tollList.totalAmount')).getByText(money('10.50'))).toBeInTheDocument()        // total via REAL formatCurrency
    expect(within(tile('tollList.averagePerTransaction')).getByText(money(5.25))).toBeInTheDocument() // average = 10.50 / 2 = $5.25
  })

  it('renders the transaction card location + amount via the REAL formatCurrency (fails if the card amount Mono is dropped or renders the wrong value)', () => {
    render(<TollTransactionList {...PROPS} />)
    // The txn card is OUTSIDE the monthly table and exists pre-restyle → GREEN + sabotage-proven; queried
    // directly, never scoped through monthlyTable() (R2-M1).
    expect(screen.getByText('Beltway Plaza')).toBeInTheDocument()
    expect(screen.getByText(money(3.75))).toBeInTheDocument()
  })

  it('clicking a transaction-card Edit calls onEditClick with THE WHOLE transaction (fails if edit is unwired or passes a truncated object)', () => {
    render(<TollTransactionList {...PROPS} />)
    fireEvent.click(screen.getByRole('button', { name: 'common:edit' }))
    expect(onEditClick).toHaveBeenCalledWith(txn)
  })

  it('clicking a transaction-card Delete (confirm accepted) calls the delete mutation with the id (fails if delete is unwired or the confirm gate is dropped)', async () => {
    render(<TollTransactionList {...PROPS} />)
    fireEvent.click(screen.getByRole('button', { name: 'common:delete' }))
    await answerConfirm('confirm', 'tollList.confirmDelete')
    expect(deleteMutate).toHaveBeenCalledWith(1, expect.anything())
  })

  it('clicking a transaction-card Delete with confirm REJECTED does NOT call the delete mutation (B4: fails if the handler ignores a false confirm and deletes anyway)', async () => {
    render(<TollTransactionList {...PROPS} />)
    fireEvent.click(screen.getByRole('button', { name: 'common:delete' }))
    await answerConfirm('cancel', 'tollList.confirmDelete')
    expect(deleteMutate).not.toHaveBeenCalled()
  })

  it('the transaction-card Edit/Delete expose a real aria-label (IconButton), not a bare title (fails if IconButton regresses to a title-only <button>)', () => {
    render(<TollTransactionList {...PROPS} />)
    expect(screen.getByRole('button', { name: 'common:edit' })).toHaveAttribute('aria-label', 'common:edit')
    expect(screen.getByRole('button', { name: 'common:delete' })).toHaveAttribute('aria-label', 'common:delete')
  })
})

describe('TollTransactionList — monthly breakdown DataTable', () => {
  it('renders EVERY monthly column render-transform INSIDE the named DataTable — the REAL formatted month, the count, and the currency total (M2 — fails if a column render is dropped or the scoping breaks)', () => {
    render(<TollTransactionList {...PROPS} />)
    // Real formatter output (dateLocale mocked undefined ⇒ same call the column render makes), not a hard-coded literal.
    const monthLabel = formatDateForDisplay('2026-02-01', { year: 'numeric', month: 'long' })
    expect(within(monthlyTable()).getByText(monthLabel)).toBeInTheDocument()          // month column
    expect(within(monthlyTable()).getByText('1')).toBeInTheDocument()                 // count column (monthly count 1)
    expect(within(monthlyTable()).getByText(money(7.25))).toBeInTheDocument()         // total column
  })

  it('NONE of the tile values or the txn-card amount leak INTO the monthly table (M1 non-leak — fails if a value cross-renders into the monthly table)', () => {
    render(<TollTransactionList {...PROPS} />)
    // Distinct fixtures (monthly count 1, total $7.25) so a leak is unambiguous. This check NEEDS the caption'd
    // table → RED pre-restyle (the raw monthly table has NO accessible name, so monthlyTable() throws), GREEN
    // once the DataTable adds <caption class="sr-only"> (R2-M1 — correctly RED→GREEN across the restyle).
    expect(within(monthlyTable()).queryByText('2')).not.toBeInTheDocument()            // tile count
    expect(within(monthlyTable()).queryByText(money('10.50'))).not.toBeInTheDocument() // tile total
    expect(within(monthlyTable()).queryByText(money(5.25))).not.toBeInTheDocument()    // tile average
    expect(within(monthlyTable()).queryByText(money(3.75))).not.toBeInTheDocument()    // txn-card amount
  })

  it('exposes EXACTLY ONE table role — the monthly DataTable — so no legacy raw <table> lingers (B6 — fails if the old raw table is left in place beside the DataTable)', () => {
    render(<TollTransactionList {...PROPS} />)
    expect(screen.getAllByRole('table')).toHaveLength(1)
  })
})

describe('TollTransactionList — empty state', () => {
  it('with zero transactions, the empty-state CTA fires onAddClick (fails if the CTA is unwired or the title text changes)', () => {
    useTollTransactionsMock.mockReturnValue({ data: { transactions: [] }, isLoading: false, error: null })
    useTollTransactionSummaryMock.mockReturnValue({ data: undefined })
    render(<TollTransactionList {...PROPS} />)
    expect(screen.getByText('tollList.noRecords')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'tollList.addFirstTransaction' }))
    expect(onAddClick).toHaveBeenCalled()
  })
})
