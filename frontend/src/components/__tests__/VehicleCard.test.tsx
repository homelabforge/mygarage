import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '../../__tests__/test-utils'
import VehicleCard from '../VehicleCard'
import type { Vehicle, VehicleType } from '../../types/vehicle'

// Mock i18n-dependent hooks so VehicleCard doesn't need AuthProvider/i18next
vi.mock('../../hooks/useDateLocale', () => ({
  useDateLocale: () => 'en-US',
}))

vi.mock('../../hooks/useCurrencyPreference', () => ({
  useCurrencyPreference: () => ({
    currencyCode: 'USD',
    locale: 'en-US',
    formatCurrency: () => '$0.00',
  }),
}))

describe('VehicleCard', () => {
  const mockVehicle: Vehicle = {
    vin: '1HGBH41JXMN109186',
    year: 2018,
    make: 'Honda',
    model: 'Accord',
    trim: 'Sport',
    nickname: 'Daily Driver',
    license_plate: 'ABC123',
    vehicle_type: 'Car' as VehicleType,
    purchase_date: '2020-01-15',
    purchase_price: '25000',
    created_at: '2020-01-15T00:00:00Z',
    archived_visible: true,
  }

  it('renders vehicle information', () => {
    render(<VehicleCard vehicle={mockVehicle} />)

    expect(screen.getByText(/Daily Driver/i)).toBeInTheDocument()
    expect(screen.getByText(/2018 Honda Accord/i)).toBeInTheDocument()
  })

  it('displays placeholder when no photo', () => {
    render(<VehicleCard vehicle={mockVehicle} />)

    // Should show Car icon as placeholder
    const carIcon = document.querySelector('svg')
    expect(carIcon).toBeInTheDocument()
  })

  it('displays purchase price formatted', () => {
    render(<VehicleCard vehicle={mockVehicle} />)

    expect(screen.getByText(/\$25,000/i)).toBeInTheDocument()
  })

  it('links to vehicle detail page', () => {
    const { container } = render(<VehicleCard vehicle={mockVehicle} />)

    const link = container.querySelector('a')
    expect(link).toHaveAttribute('href', `/vehicles/${mockVehicle.vin}`)
  })
})
