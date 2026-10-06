import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { fireEvent, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { render, screen } from '../../__tests__/test-utils'
import type { Supply } from '../../types/supplies'

// Mock the supplies query hooks so this stays a unit test — no real network
// calls needed. The api layer itself is already mocked globally (setup.ts
// mocks axios), so any hook we don't mock here still resolves harmlessly.
const useSupplyHistoryMock = vi.fn()
const mutationStub = () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false, variables: undefined })
// Stable across renders so a test can read back what the form posted.
const addPurchaseMock = vi.fn()
const addAdjustmentMock = vi.fn()

vi.mock('../../hooks/queries/useSupplies', () => ({
  useSupplyHistory: () => useSupplyHistoryMock(),
  useAddPurchase: () => ({ ...mutationStub(), mutateAsync: addPurchaseMock }),
  useDeletePurchase: () => mutationStub(),
  useAddAdjustment: () => ({ ...mutationStub(), mutateAsync: addAdjustmentMock }),
  useDeleteAdjustment: () => mutationStub(),
  useUploadReceipt: () => mutationStub(),
  useDeleteReceipt: () => mutationStub(),
}))

// Same mock pattern as Supplies.test.tsx — these hooks need AuthProvider
// otherwise, and it's not under test here.
const unitMock = vi.hoisted(() => ({ system: 'metric' as 'metric' | 'imperial' }))
vi.mock('../../hooks/useUnitPreference', () => ({
  useUnitPreference: () => ({ system: unitMock.system, showBoth: false }),
}))
// The REAL currency hook runs, so a rate option has to survive it. Only the
// signed-in user is faked, and the rate-digits test flips them to yen.
const currencyMock = vi.hoisted(() => ({ code: 'USD' }))
vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({ user: { currency_code: currencyMock.code } }),
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
  currencyMock.code = 'USD'
  unitMock.system = 'metric'
  useSupplyHistoryMock.mockReturnValue({
    data: { supply_id: 1, on_hand: '3.500', avg_unit_cost: '5.25', entries: mockEntries },
    isLoading: false,
    error: null,
  })
  addPurchaseMock.mockResolvedValue({ id: 99 })
  addAdjustmentMock.mockResolvedValue({ id: 98 })
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('SupplyHistoryModal initialForm', () => {
  // The Drawer under FormModalWrapper portals the dialog out of `container`,
  // so these go through document, like the page tests do.
  it('initialForm="purchase" shows the purchase form immediately', () => {
    render(<SupplyHistoryModal supply={mockSupply} onClose={vi.fn()} initialForm="purchase" />)
    expect(document.getElementById('purchase-date')).not.toBeNull()
  })

  it('initialForm="adjustment" shows the adjustment form immediately', () => {
    render(<SupplyHistoryModal supply={mockSupply} onClose={vi.fn()} initialForm="adjustment" />)
    expect(document.getElementById('adjustment-quantity')).not.toBeNull()
  })

  it('omitted keeps both forms closed', () => {
    render(<SupplyHistoryModal supply={mockSupply} onClose={vi.fn()} />)
    expect(document.getElementById('purchase-date')).toBeNull()
    expect(document.getElementById('adjustment-quantity')).toBeNull()
  })
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

  it('shows a yen average unit cost with its decimals, and ledger costs as whole yen', () => {
    // The average unit cost is a rate; the ledger costs are totals.
    currencyMock.code = 'JPY'
    useSupplyHistoryMock.mockReturnValue({
      data: { supply_id: 1, on_hand: '3.500', avg_unit_cost: '170.5', entries: mockEntries },
      isLoading: false,
      error: null,
    })
    render(<SupplyHistoryModal supply={mockSupply} onClose={vi.fn()} />)

    expect(screen.getByText('¥170.50')).toBeInTheDocument()
    expect(screen.queryByText('¥171')).not.toBeInTheDocument()
    expect(screen.getByRole('dialog').textContent ?? '').toContain('¥25')
  })

  it('prices a quart in the header for an imperial user', () => {
    // 5 qt for $25 is stored as 4.732 L, so the API's average is $5.2832 per litre.
    unitMock.system = 'imperial'
    useSupplyHistoryMock.mockReturnValue({
      data: { supply_id: 1, on_hand: '4.732', avg_unit_cost: String(25 / 4.732), entries: mockEntries },
      isLoading: false,
      error: null,
    })
    render(<SupplyHistoryModal supply={mockSupply} onClose={vi.fn()} />)

    expect(screen.getByText('5.00 qt')).toBeInTheDocument()
    expect(screen.getByText('$5.00')).toBeInTheDocument()
    expect(screen.queryByText('$5.28')).not.toBeInTheDocument()
    expect(screen.getByText('supplies.avgCostPerUnit')).toBeInTheDocument()
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

  // Task 8: the adjustment/purchase quantity fields keep RHF's native
  // `required`/`min` rules (no zod resolver on these two inline forms), while
  // the field itself now runs through `registerDecimal`, whose `setValueAs`
  // can hand RHF the `INVALID_NUMBER` symbol for unparseable text. RHF's
  // built-in min/max check coerces the field value with unary `+`, which
  // throws a TypeError on a Symbol — so unparseable text must never reach
  // that check. These prove it doesn't crash and surfaces a real message.
  it('rejects unparseable text in the adjustment quantity field without crashing', async () => {
    const user = userEvent.setup()
    render(<SupplyHistoryModal supply={mockSupply} onClose={vi.fn()} />)

    await user.click(screen.getByText('supplies.history.logAdjustment'))
    const quantityInput = screen.getByLabelText(/supplies\.history\.quantity/)
    await user.type(quantityInput, 'abc')
    await user.click(screen.getByRole('button', { name: 'save' }))

    await waitFor(() => {
      expect(screen.getByText('supplies.history.quantityRequired')).toBeInTheDocument()
    })
  })

  it('rejects unparseable text in the purchase quantity field without crashing', async () => {
    const user = userEvent.setup()
    render(<SupplyHistoryModal supply={mockSupply} onClose={vi.fn()} />)

    await user.click(screen.getByText('supplies.history.logPurchase'))
    const quantityInput = screen.getByLabelText(/supplies\.history\.quantity/)
    await user.type(quantityInput, 'abc')
    await user.click(screen.getByRole('button', { name: 'save' }))

    await waitFor(() => {
      expect(screen.getByText('supplies.history.quantityRequired')).toBeInTheDocument()
    })
  })

  // IMPORTANT (review response): total_cost is optional, so it never had a
  // `required` rule — but it DID rely on the native `min="0"` HTML attribute
  // (dropped in Task 8, since it's inert on the migrated type="text" field)
  // with nothing to replace it, so a negative total_cost silently reached
  // the API with no client-side error. Now uses the same validate-function
  // treatment as quantity above (a literal `min` rule would crash the same
  // way on unparseable text).
  it('rejects a negative total_cost with a field error instead of letting it reach the API', async () => {
    const user = userEvent.setup()
    render(<SupplyHistoryModal supply={mockSupply} onClose={vi.fn()} />)

    await user.click(screen.getByText('supplies.history.logPurchase'))
    await user.type(screen.getByLabelText(/supplies\.history\.quantity/), '2')
    await user.type(screen.getByLabelText('totalCost'), '-5')
    await user.click(screen.getByRole('button', { name: 'save' }))

    await waitFor(() => {
      expect(screen.getByText('common:validation.amount.negative')).toBeInTheDocument()
    })
  })

  // money-fits: the API caps a purchase total at MONEY_MAX (9,999,999,999.99).
  it('rejects a total_cost past MONEY_MAX with a field error', async () => {
    const user = userEvent.setup()
    render(<SupplyHistoryModal supply={mockSupply} onClose={vi.fn()} />)

    await user.click(screen.getByText('supplies.history.logPurchase'))
    await user.type(screen.getByLabelText(/supplies\.history\.quantity/), '2')
    await user.type(screen.getByLabelText('totalCost'), '10000000000')
    await user.click(screen.getByRole('button', { name: 'save' }))

    await waitFor(() => {
      expect(screen.getByText('common:validation.amount.tooLarge')).toBeInTheDocument()
    })
  })

  // Text that isn't a number says so. It used to get the "cannot be negative"
  // message, which is wrong for "abc"; moneyError gives the invalid one.
  it('rejects unparseable text in the purchase total_cost field without crashing', async () => {
    const user = userEvent.setup()
    render(<SupplyHistoryModal supply={mockSupply} onClose={vi.fn()} />)

    await user.click(screen.getByText('supplies.history.logPurchase'))
    await user.type(screen.getByLabelText(/supplies\.history\.quantity/), '2')
    await user.type(screen.getByLabelText('totalCost'), 'abc')
    await user.click(screen.getByRole('button', { name: 'save' }))

    await waitFor(() => {
      expect(screen.getByText('common:validation.amount.invalid')).toBeInTheDocument()
    })
  })
})

describe('SupplyHistoryModal: the supply keeps its own unit', () => {
  // The metric mock alone would give L, so every mL below comes from the token.
  const mlSupply = { ...mockSupply, volume_unit: 'mL' } as Supply

  it('the purchase quantity label carries the supply unit', () => {
    render(<SupplyHistoryModal supply={mlSupply} onClose={vi.fn()} initialForm="purchase" />)

    expect(screen.getByLabelText(/supplies\.history\.quantity \(mL\)/)).toBe(
      document.getElementById('purchase-quantity'),
    )
  })

  it('the header and ledger rows read in whole mL', () => {
    render(<SupplyHistoryModal supply={mlSupply} onClose={vi.fn()} />)
    const dialogText = screen.getByRole('dialog').textContent ?? ''

    expect(screen.getByText('3,500 mL')).toBeInTheDocument()
    expect(dialogText).toContain('+5,000 mL')
    expect(dialogText).toContain('-1,000 mL')
    expect(dialogText).toContain('-500 mL')
    expect(dialogText).not.toContain('+5.00 L')
  })

  it('a few mL in litres read as 0.00x L, header and ledger', () => {
    useSupplyHistoryMock.mockReturnValue({
      data: {
        supply_id: 1,
        on_hand: '0.003',
        avg_unit_cost: '5.25',
        entries: [
          { ...mockEntries[0], quantity: '0.004', running_balance: '0.004' },
          { ...mockEntries[2], quantity: '-0.001', running_balance: '0.003' },
        ],
      },
      isLoading: false,
      error: null,
    })
    render(<SupplyHistoryModal supply={{ ...mockSupply, on_hand: '0.003' }} onClose={vi.fn()} />)
    const dialogText = screen.getByRole('dialog').textContent ?? ''

    expect(dialogText).toContain('+0.004 L')
    expect(dialogText).toContain('-0.001 L')
    expect(dialogText).toContain('0.003 L')
    expect(dialogText).not.toContain('0.00 L')
  })

  it('the header prices per mL to four places', () => {
    // History says $5.25/L, which is $0.00525/mL.
    render(<SupplyHistoryModal supply={mlSupply} onClose={vi.fn()} />)

    expect(screen.getByText('$0.0053')).toBeInTheDocument()
    expect(screen.queryByText('$0.01')).not.toBeInTheDocument()
  })

  it('a purchase under 1 mL is refused as too small to store', async () => {
    const user = userEvent.setup()
    render(<SupplyHistoryModal supply={mlSupply} onClose={vi.fn()} initialForm="purchase" />)

    await user.type(screen.getByLabelText(/supplies\.history\.quantity/), '0.4')
    await user.click(screen.getByRole('button', { name: 'save' }))

    await waitFor(() => {
      expect(screen.getByText('supplies.history.quantityTooSmall')).toBeInTheDocument()
    })
    expect(addPurchaseMock).not.toHaveBeenCalled()
  })

  it('zero still asks for a quantity above 0, not the too-small message', async () => {
    const user = userEvent.setup()
    render(<SupplyHistoryModal supply={mlSupply} onClose={vi.fn()} initialForm="purchase" />)

    await user.type(screen.getByLabelText(/supplies\.history\.quantity/), '0')
    await user.click(screen.getByRole('button', { name: 'save' }))

    await waitFor(() => {
      expect(screen.getByText('supplies.history.quantityRequired')).toBeInTheDocument()
    })
    expect(screen.queryByText('supplies.history.quantityTooSmall')).not.toBeInTheDocument()
    expect(addPurchaseMock).not.toHaveBeenCalled()
  })

  it('250 mL posts 0.25 L', async () => {
    const user = userEvent.setup()
    render(<SupplyHistoryModal supply={mlSupply} onClose={vi.fn()} initialForm="purchase" />)

    await user.type(screen.getByLabelText(/supplies\.history\.quantity/), '250')
    await user.click(screen.getByRole('button', { name: 'save' }))

    await waitFor(() => {
      expect(addPurchaseMock).toHaveBeenCalledTimes(1)
    })
    expect(addPurchaseMock.mock.calls[0][0].quantity).toBeCloseTo(0.25, 9)
  })

  it('a 500 mL adjustment posts 0.5 L', async () => {
    const user = userEvent.setup()
    render(<SupplyHistoryModal supply={mlSupply} onClose={vi.fn()} initialForm="adjustment" />)

    await user.type(screen.getByLabelText(/supplies\.history\.quantity/), '500')
    await user.click(screen.getByRole('button', { name: 'save' }))

    await waitFor(() => {
      expect(addAdjustmentMock).toHaveBeenCalledTimes(1)
    })
    expect(addAdjustmentMock.mock.calls[0][0].quantity).toBeCloseTo(0.5, 9)
  })
})
