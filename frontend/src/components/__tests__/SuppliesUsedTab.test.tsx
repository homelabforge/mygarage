import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen } from '../../__tests__/test-utils'
import type { SupplyUsage } from '../../types/supplies'

// Mock the query hook so this is a unit test — no real network calls.
const useVehicleSupplyUsagesMock = vi.fn()

vi.mock('../../hooks/queries/useSupplies', () => ({
  useVehicleSupplyUsages: () => useVehicleSupplyUsagesMock(),
}))

vi.mock('../../hooks/useCurrencyPreference', () => ({
  useCurrencyPreference: () => ({
    currencyCode: 'USD',
    locale: 'en-US',
    formatCurrency: (value: unknown) => (value == null ? '-' : `$${value}`),
  }),
}))

vi.mock('../../hooks/useUnitPreference', () => ({
  useUnitPreference: () => ({ system: 'metric' }),
}))

vi.mock('../../hooks/useDateLocale', () => ({
  useDateLocale: () => 'en-US',
}))

import SuppliesUsedTab from '../SuppliesUsedTab'

const mockUsages: SupplyUsage[] = [
  {
    id: 1,
    supply_id: 10,
    supply_name: 'Motor Oil 5W-30',
    unit_type: 'volume',
    quantity: '4.500',
    cost_snapshot: '22.50',
    unit_cost_snapshot: '5.00',
    service_line_item_id: 3,
    service_visit_id: 7,
    service_visit_date: '2026-01-10',
    created_at: '2026-01-10T00:00:00',
  },
  {
    id: 2,
    supply_id: 11,
    supply_name: 'Oil Filter',
    unit_type: 'count',
    quantity: '1.000',
    cost_snapshot: null,
    unit_cost_snapshot: null,
    service_line_item_id: 4,
    service_visit_id: null,
    service_visit_date: null,
    created_at: '2026-01-10T00:00:00',
  },
]

beforeEach(() => {
  vi.clearAllMocks()
  useVehicleSupplyUsagesMock.mockReturnValue({
    data: { usages: mockUsages, total: mockUsages.length },
    isLoading: false,
    error: null,
  })
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('SuppliesUsedTab', () => {
  it('renders each usage with supply name, quantity, and cost', () => {
    render(<SuppliesUsedTab vin="1HGCM82633A004352" />)

    expect(screen.getByText('Motor Oil 5W-30')).toBeInTheDocument()
    expect(screen.getByText('Oil Filter')).toBeInTheDocument()
    expect(screen.getByText('$22.50')).toBeInTheDocument()
    expect(screen.getByText(/4\.5/)).toBeInTheDocument()
  })

  it('links a usage with a service_visit_id to the service tab, guards rows without one', () => {
    render(<SuppliesUsedTab vin="1HGCM82633A004352" />)

    const links = screen.getAllByText('supplies.usedTab.viewVisit')
    expect(links).toHaveLength(1)
    expect(links[0].closest('a')).toHaveAttribute('href', '/vehicles/1HGCM82633A004352?tab=service')
  })

  it('shows the loading state while usages are fetching', () => {
    useVehicleSupplyUsagesMock.mockReturnValue({ data: undefined, isLoading: true, error: null })
    render(<SuppliesUsedTab vin="1HGCM82633A004352" />)

    expect(screen.getByText('supplies.usedTab.loading')).toBeInTheDocument()
  })

  it('shows the empty state when there are no usages', () => {
    useVehicleSupplyUsagesMock.mockReturnValue({
      data: { usages: [], total: 0 },
      isLoading: false,
      error: null,
    })
    render(<SuppliesUsedTab vin="1HGCM82633A004352" />)

    expect(screen.getByText('supplies.usedTab.empty')).toBeInTheDocument()
  })

  it('shows an error message when the fetch fails', () => {
    useVehicleSupplyUsagesMock.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error('boom'),
    })
    render(<SuppliesUsedTab vin="1HGCM82633A004352" />)

    expect(screen.getByText('boom')).toBeInTheDocument()
  })
})
