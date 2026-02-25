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

// Mock unit preference hook (requires AuthProvider otherwise)
vi.mock('../../hooks/useUnitPreference', () => ({
  useUnitPreference: () => ({ system: 'imperial', showBoth: false }),
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

  // The mileage label renders as "Mileage (mi)" — match on the leading word
  const hasMileage = () => screen.queryByText(/^mileage/i) !== null

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
