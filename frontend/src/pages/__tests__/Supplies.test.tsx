import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '../../__tests__/test-utils'
import type { Supply } from '../../types/supplies'

// Mock the supplies query hooks so this stays a unit test — no real network
// calls needed. The api layer itself is already mocked globally (setup.ts
// mocks axios), so any hook we don't mock here still resolves harmlessly.
const useSuppliesMock = vi.fn()
const useDeleteSupplyMock = vi.fn()

vi.mock('../../hooks/queries/useSupplies', () => ({
  useSupplies: () => useSuppliesMock(),
  useCreateSupply: () => ({ mutateAsync: vi.fn(), mutate: vi.fn(), isPending: false }),
  useUpdateSupply: () => ({ mutateAsync: vi.fn(), mutate: vi.fn(), isPending: false }),
  useDeleteSupply: () => useDeleteSupplyMock(),
}))

vi.mock('../../hooks/queries/useQuickEntryVehicles', () => ({
  useQuickEntryVehicles: () => ({ data: [], isLoading: false }),
}))

// Same mock pattern as DEFRecordList.test.tsx — these hooks need AuthProvider
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

import Supplies from '../Supplies'

const mockSupply: Supply = {
  id: 1,
  name: 'Motor Oil 5W-30',
  unit_type: 'volume',
  category: 'Fluids',
  part_number: 'MO-530',
  vin: null,
  notes: null,
  on_hand: '10.500',
  avg_unit_cost: '5.25',
  is_active: true,
  is_negative: false,
  created_at: '2026-01-01T00:00:00',
  updated_at: null,
} as Supply

beforeEach(() => {
  vi.clearAllMocks()
  useSuppliesMock.mockReturnValue({
    data: { supplies: [mockSupply], total: 1 },
    isLoading: false,
    error: null,
  })
  useDeleteSupplyMock.mockReturnValue({
    mutate: vi.fn(),
    isPending: false,
    variables: undefined,
  })
})

describe('Supplies page', () => {
  it('renders the supply list from useSupplies', () => {
    render(<Supplies />)

    expect(screen.getByText('Motor Oil 5W-30')).toBeInTheDocument()
    expect(screen.getByText('Fluids')).toBeInTheDocument()
    expect(screen.getByText('MO-530')).toBeInTheDocument()
  })

  it('shows the empty state when there are no supplies', () => {
    useSuppliesMock.mockReturnValue({ data: { supplies: [], total: 0 }, isLoading: false, error: null })
    render(<Supplies />)

    expect(screen.getByText('supplies.noSupplies')).toBeInTheDocument()
  })

  it('opens the form modal when "Add supply" is clicked', () => {
    render(<Supplies />)

    // Select by id, not label text — the global i18n test mock renders keys,
    // so the form isn't visible until the click; the name input only exists
    // once the modal has mounted.
    expect(document.getElementById('name')).not.toBeInTheDocument()

    fireEvent.click(screen.getByText('supplies.addSupply'))

    expect(document.getElementById('name')).toBeInTheDocument()
    expect(document.getElementById('unit_type')).toBeInTheDocument()
    // unit_type is only disabled in edit mode — create mode leaves it editable
    expect(document.getElementById('unit_type')).not.toBeDisabled()
  })

  it('disables unit_type when editing an existing supply', () => {
    render(<Supplies />)

    fireEvent.click(screen.getByLabelText('common:edit'))

    expect(document.getElementById('unit_type')).toBeDisabled()
    // is_active toggle only appears on edit
    expect(document.getElementById('is_active')).toBeInTheDocument()
  })
})
