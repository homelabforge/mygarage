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

// Switchable, so a legacy row can be shown to follow the system and a tokened row not to.
const unitPref = vi.hoisted(() => ({ system: 'metric' as 'metric' | 'imperial' }))

vi.mock('../../hooks/useUnitPreference', () => ({
  useUnitPreference: () => ({ system: unitPref.system }),
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
  unitPref.system = 'metric'
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

    // Final-review I3: this render used to be raw `error.message` (a plain
    // `Error('boom')` would print the literal string "boom" — informative by
    // luck for THIS error shape, but any AxiosError variable named `error`
    // instead of `err` was invisible to the original completion grep and
    // still printed "Request failed with status code NNN"). Routed through
    // getActionErrorMessage like every other query-error render in the app;
    // asserted as the literal, un-interpolated translated template since
    // this suite's i18next singleton isn't initialized outside a rendered
    // component (see ReminderForm.test.tsx:114 for the same pattern).
    expect(screen.getByText('Failed to {{action}}. {{message}}')).toBeInTheDocument()
  })

  describe('each usage shows its own supply unit', () => {
    const ADDITIVE: SupplyUsage = {
      id: 3,
      supply_id: 12,
      supply_name: 'Fuel Additive',
      unit_type: 'volume',
      volume_unit: 'mL',
      quantity: '0.250',
      cost_snapshot: '3.00',
      unit_cost_snapshot: '12.00',
      service_line_item_id: 5,
      service_visit_id: 8,
      service_visit_date: '2026-02-01',
      created_at: '2026-02-01T00:00:00',
    }

    beforeEach(() => {
      const usages = [ADDITIVE, ...mockUsages]
      useVehicleSupplyUsagesMock.mockReturnValue({
        data: { usages, total: usages.length },
        isLoading: false,
        error: null,
      })
    })

    it('renders a mL usage in whole mL, and a legacy usage in the metric pick', () => {
      render(<SuppliesUsedTab vin="1HGCM82633A004352" />)

      expect(screen.getByText('250 mL')).toBeInTheDocument()
      expect(screen.getByText('4.50 L')).toBeInTheDocument()
    })

    it('moves only the legacy usage to quarts under imperial', () => {
      unitPref.system = 'imperial'
      render(<SuppliesUsedTab vin="1HGCM82633A004352" />)

      // 4.5 L is 4.755 US qt; the stored mL token ignores the system.
      expect(screen.getByText('4.76 qt')).toBeInTheDocument()
      expect(screen.getByText('250 mL')).toBeInTheDocument()
    })
  })
})
