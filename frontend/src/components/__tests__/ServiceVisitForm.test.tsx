import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '../../__tests__/test-utils'
import ServiceVisitForm from '../ServiceVisitForm'
import type { VehicleType } from '../../types/vehicle'

// Mock API to suppress network calls
vi.mock('../../services/api', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ data: { items: [] } }),
    post: vi.fn().mockResolvedValue({ data: {} }),
    put: vi.fn().mockResolvedValue({ data: {} }),
  },
}))

// Mock unit preference hook (requires AuthProvider otherwise). The resolved
// set is supplied too: `useUnitFormat` reads `units`, and a mock that gave only
// the collapsed `system` would hand the form an undefined set. Mixed sets,
// where `system` and `units.distance` disagree, are exercised in
// ServiceVisitForm.mixedUnits.test.tsx.
vi.mock('../../hooks/useUnitPreference', async () => {
  const { IMPERIAL_UNITS } = await import('@/__tests__/factories')
  return {
    useUnitPreference: () => ({
      system: 'imperial',
      showBoth: false,
      units: IMPERIAL_UNITS,
      gallonStandard: 'us',
    }),
  }
})

// Mock currency preference hook (CurrencyInputPrefix depends on it, which needs AuthProvider)
vi.mock('../../hooks/useCurrencyPreference', () => ({
  useCurrencyPreference: () => ({
    currencyCode: 'USD',
    locale: 'en-US',
    formatCurrency: () => '$0.00',
  }),
}))

// Mock components that make additional API calls or are complex to render
vi.mock('../VendorSearch', () => ({
  default: () => <div data-testid="vendor-search" />,
}))
vi.mock('../LineItemEditor', () => ({
  default: () => <div data-testid="line-item-editor" />,
}))
vi.mock('../ServiceVisitAttachmentUpload', () => ({
  default: () => <div data-testid="attachment-upload" />,
}))
vi.mock('../ServiceVisitAttachmentList', () => ({
  default: () => <div data-testid="attachment-list" />,
}))
vi.mock('sonner', () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}))

const DEFAULT_PROPS = {
  vin: 'TEST123',
  onClose: vi.fn(),
  onSuccess: vi.fn(),
}

describe('ServiceVisitForm – mileage field visibility', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  // With i18n mock, t() returns translation keys. The label renders as "common:mileage (mi)"
  const hasMileage = () => screen.queryByText(/mileage/i) !== null

  it('shows mileage field when vehicleType is undefined (default to motorized)', () => {
    render(<ServiceVisitForm {...DEFAULT_PROPS} />)
    expect(hasMileage()).toBe(true)
  })

  it.each(['Car', 'Truck', 'SUV', 'Motorcycle', 'RV', 'Electric', 'Hybrid'] as VehicleType[])(
    'shows mileage field for motorized type: %s',
    (vehicleType) => {
      render(<ServiceVisitForm {...DEFAULT_PROPS} vehicleType={vehicleType} />)
      expect(hasMileage()).toBe(true)
    }
  )

  it.each(['Trailer', 'FifthWheel', 'TravelTrailer'] as VehicleType[])(
    'hides mileage field for non-motorized type: %s',
    (vehicleType) => {
      render(<ServiceVisitForm {...DEFAULT_PROPS} vehicleType={vehicleType} />)
      expect(hasMileage()).toBe(false)
    }
  )
})
