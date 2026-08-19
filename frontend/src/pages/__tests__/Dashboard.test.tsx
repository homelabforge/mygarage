import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '../../__tests__/test-utils'
import Dashboard from '../Dashboard'

vi.mock('../../services/api', () => ({
  default: {
    get: vi.fn(() =>
      Promise.resolve({
        data: {
          total_vehicles: 0,
          vehicles: [],
          multi_user_enabled: false,
          total_service_records: 0,
          total_fuel_records: 0,
          total_maintenance_items: 0,
          total_documents: 0,
          total_notes: 0,
          total_photos: 0,
          fleet_health: null,
        },
      }),
    ),
  },
}))

vi.mock('../../services/externalVehicleService', () => ({
  listExternalVehicles: vi.fn().mockResolvedValue({ vehicles: [], total: 0 }),
}))

vi.mock('../../components/VehicleWizard', () => ({ default: () => null }))

describe('Dashboard Page', () => {
  it('renders dashboard header', () => {
    render(<Dashboard />)

    // With i18n mock, t() returns translation keys
    expect(screen.getByText('dashboard.title')).toBeInTheDocument()
  })

  it('has add vehicle button', () => {
    render(<Dashboard />)

    // With i18n mock, button text is the translation key
    expect(screen.getByRole('button', { name: /dashboard\.addVehicle/i })).toBeInTheDocument()
  })
})
