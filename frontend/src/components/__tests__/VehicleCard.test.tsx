import { describe, it, expect } from 'vitest'
import { render, screen } from '../../__tests__/test-utils'
import VehicleCard from '../VehicleCard'
import type { VehicleType } from '../../types/vehicle'

describe('VehicleCard', () => {
  const mockVehicle = {
    id: 1,
    vin: '1HGBH41JXMN109186',
    year: 2018,
    make: 'Honda',
    model: 'Accord',
    trim: 'Sport',
    nickname: 'Daily Driver',
    license_plate: 'ABC123',
    vehicle_type: 'Car' as VehicleType,
    current_odometer: 45000,
    purchase_date: '2020-01-15',
    purchase_price: 25000,
    main_photo: undefined,
    created_at: '2020-01-15T00:00:00Z',
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
