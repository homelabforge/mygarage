import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { fireEvent } from '@testing-library/react'
import { render, screen } from '../../__tests__/test-utils'
import type { Supply } from '../../types/supplies'

// Mock the supplies query hooks so this stays a unit test — no real network
// calls needed. The api layer itself is already mocked globally (setup.ts
// mocks axios), so any hook we don't mock here still resolves harmlessly.
const useSupplyHistoryMock = vi.fn()
const mutationStub = () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false, variables: undefined })

vi.mock('../../hooks/queries/useSupplies', () => ({
  useSupplyHistory: () => useSupplyHistoryMock(),
  useAddPurchase: () => mutationStub(),
  useDeletePurchase: () => mutationStub(),
  useAddAdjustment: () => mutationStub(),
  useDeleteAdjustment: () => mutationStub(),
  useUploadReceipt: () => mutationStub(),
  useDeleteReceipt: () => mutationStub(),
}))

// Same mock pattern as Supplies.test.tsx — these hooks need AuthProvider
// otherwise, and it's not under test here.
vi.mock('../../hooks/useUnitPreference', () => ({
  useUnitPreference: () => ({ system: 'metric', showBoth: false }),
}))
vi.mock('../../hooks/useCurrencyPreference', () => ({
  useCurrencyPreference: () => ({
    currencyCode: 'USD',
    locale: 'en-US',
    formatCurrency: () => '$5.25',
  }),
}))

import SupplyHistoryModal from '../SupplyHistoryModal'

const mockSupply: Supply = {
  id: 1,
  name: 'Motor Oil 5W-30',
  unit_type: 'volume',
  category: 'Fluids',
  part_number: 'MO-530',
  vin: null,
  notes: null,
  on_hand: '3.500',
  avg_unit_cost: '5.25',
  is_active: true,
  is_negative: false,
  created_at: '2026-01-01T00:00:00',
  updated_at: null,
} as Supply

// Chronological ledger: purchase (+5.000) then two usages (-1.000, -0.500),
// running balance climbing/falling in order, matching the backend's
// forward-accumulated ledger (see supply_service.get_supply_history).
const mockEntries = [
  {
    entry_type: 'purchase',
    id: 10,
    at: '2026-01-05T00:00:00',
    quantity: '5.000',
    running_balance: '5.000',
    cost: '25.00',
    receipt: null,
    supplier_id: null,
  },
  {
    entry_type: 'usage',
    id: 20,
    at: '2026-01-10T00:00:00',
    quantity: '-1.000',
    running_balance: '4.000',
    cost: '5.25',
    service_line_item_id: 3,
    service_visit_id: 7,
    service_visit_date: '2026-01-10',
  },
  {
    entry_type: 'usage',
    id: 21,
    at: '2026-01-12T00:00:00',
    quantity: '-0.500',
    running_balance: '3.500',
    cost: null,
    service_line_item_id: null,
    service_visit_id: null,
    service_visit_date: null,
  },
]

beforeEach(() => {
  vi.clearAllMocks()
  useSupplyHistoryMock.mockReturnValue({
    data: { supply_id: 1, on_hand: '3.500', avg_unit_cost: '5.25', entries: mockEntries },
    isLoading: false,
    error: null,
  })
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('SupplyHistoryModal', () => {
  it('renders the ledger entries from useSupplyHistory with dates and running balances', () => {
    render(<SupplyHistoryModal supply={mockSupply} onClose={vi.fn()} />)
    const dialogText = screen.getByRole('dialog').textContent ?? ''

    // Purchase entry: date, signed quantity, running balance.
    expect(dialogText).toContain('Jan 5, 2026')
    expect(dialogText).toContain('+5.00 L')

    // Job-tied usage entry: date, signed (negative) quantity, running balance.
    expect(dialogText).toContain('Jan 10, 2026')
    expect(dialogText).toContain('-1.00 L')
    expect(dialogText).toContain('4.00 L')

    // Standalone adjustment entry: date, signed quantity, running balance.
    expect(dialogText).toContain('Jan 12, 2026')
    expect(dialogText).toContain('-0.50 L')
    expect(dialogText).toContain('3.50 L')
  })

  it('labels a job-tied usage as a job and a standalone usage as an adjustment', () => {
    render(<SupplyHistoryModal supply={mockSupply} onClose={vi.fn()} />)

    expect(screen.getAllByText('supplies.history.job')).toHaveLength(1)
    expect(screen.getAllByText('supplies.history.adjustment')).toHaveLength(1)
    expect(screen.getAllByText('supplies.history.purchase')).toHaveLength(1)
  })

  it('only shows a delete action for the standalone adjustment, not the job-tied usage', () => {
    render(<SupplyHistoryModal supply={mockSupply} onClose={vi.fn()} />)

    // One delete-adjustment button (standalone, id 21) + one delete-purchase button (id 10).
    expect(screen.getAllByLabelText('supplies.history.deleteAdjustment')).toHaveLength(1)
    expect(screen.getAllByLabelText('supplies.history.deletePurchase')).toHaveLength(1)
  })

  it('shows an upload control (not a download link) for a purchase without a receipt', () => {
    render(<SupplyHistoryModal supply={mockSupply} onClose={vi.fn()} />)

    expect(screen.getByLabelText('supplies.history.chooseReceipt')).toBeInTheDocument()
    expect(screen.queryByLabelText('supplies.history.downloadReceipt')).not.toBeInTheDocument()
  })

  it('shows the on-hand and average unit cost header', () => {
    render(<SupplyHistoryModal supply={mockSupply} onClose={vi.fn()} />)

    expect(screen.getByText('3.50 L')).toBeInTheDocument()
    expect(screen.getAllByText('$5.25').length).toBeGreaterThan(0)
  })

  it('shows the loading state while history is fetching', () => {
    useSupplyHistoryMock.mockReturnValue({ data: undefined, isLoading: true, error: null })
    render(<SupplyHistoryModal supply={mockSupply} onClose={vi.fn()} />)

    expect(screen.getByText('supplies.history.loading')).toBeInTheDocument()
  })

  it('shows the empty state when there are no ledger entries', () => {
    useSupplyHistoryMock.mockReturnValue({
      data: { supply_id: 1, on_hand: '0.000', avg_unit_cost: null, entries: [] },
      isLoading: false,
      error: null,
    })
    render(<SupplyHistoryModal supply={mockSupply} onClose={vi.fn()} />)

    expect(screen.getByText('supplies.history.empty')).toBeInTheDocument()
  })

  it('calls onClose when the modal close button is clicked', () => {
    const onClose = vi.fn()
    render(<SupplyHistoryModal supply={mockSupply} onClose={onClose} />)

    fireEvent.click(screen.getByLabelText('common:close'))
    expect(onClose).toHaveBeenCalled()
  })
})
