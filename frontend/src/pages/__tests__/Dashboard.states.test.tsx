import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '../../__tests__/test-utils'

const mockGet = vi.fn()
vi.mock('../../services/api', () => ({
  default: { get: (...args: unknown[]) => mockGet(...args) },
}))
vi.mock('../../services/externalVehicleService', () => ({
  listExternalVehicles: vi.fn().mockResolvedValue({ vehicles: [], total: 0 }),
}))
vi.mock('../../components/VehicleStatisticsCard', () => ({
  default: ({ stats }: { stats: { vin: string } }) => (
    <div data-testid="vehicle-card">{stats.vin}</div>
  ),
}))
vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({ user: null, isAuthenticated: false }),
}))

import Dashboard from '../Dashboard'

const OK_PAYLOAD = {
  data: {
    total_vehicles: 1,
    vehicles: [
      {
        vin: 'RETRY000000000001',
        year: 2020,
        make: 'M',
        model: 'D',
        main_photo_url: null,
        vehicle_type: 'Car',
        total_service_records: 0,
        total_fuel_records: 0,
        total_odometer_records: 0,
        total_maintenance_items: 0,
        total_documents: 0,
        total_notes: 0,
        total_photos: 0,
        latest_service_date: null,
        latest_fuel_date: null,
        latest_odometer_km: null,
        latest_odometer_date: null,
        upcoming_maintenance_count: 0,
        overdue_maintenance_count: 0,
        average_l_per_100km: null,
        recent_l_per_100km: null,
        archived_at: null,
        archived_visible: false,
        is_shared_with_me: false,
        shared_by_username: null,
        share_permission: null,
      },
    ],
    total_service_records: 0,
    total_fuel_records: 0,
    total_maintenance_items: 0,
    total_documents: 0,
    total_notes: 0,
    total_photos: 0,
    fleet_health: {
      overdue_count: 0,
      upcoming_30d_count: 0,
      year: 2026,
      spent_this_year: '0.00',
      next_due: null,
    },
  },
}

const SETTINGS_OFF = {
  data: {
    settings: [
      { key: 'family_friends_enabled', value: 'false' },
    ],
  },
}

describe('Dashboard loading/error/retry states', () => {
  beforeEach(() => vi.clearAllMocks())

  it('shows the loading status region before data resolves', () => {
    // A never-resolving promise keeps the component in the loading branch.
    mockGet.mockReturnValue(new Promise(() => {}))
    render(<Dashboard />)
    expect(screen.getByRole('status')).toBeInTheDocument()
  })

  it('shows the error state, then recovers when Retry succeeds', async () => {
    mockGet.mockImplementation((url: string) => {
      if (String(url).includes('settings')) {
        return Promise.resolve(SETTINGS_OFF)
      }
      return Promise.reject(new Error('boom'))
    })
    render(<Dashboard />)

    // Error EmptyState (title = loadError key under the i18n mock) + retry button.
    expect(await screen.findByText('dashboard.loadError')).toBeInTheDocument()
    const retry = screen.getByRole('button', { name: 'common:retry' })

    // Retry now succeeds -> the grid renders the (stubbed) card, error clears.
    mockGet.mockImplementation((url: string) => {
      if (String(url).includes('settings')) {
        return Promise.resolve(SETTINGS_OFF)
      }
      return Promise.resolve(OK_PAYLOAD)
    })
    fireEvent.click(retry)

    expect(await screen.findByTestId('vehicle-card')).toBeInTheDocument()
    expect(screen.queryByText('dashboard.loadError')).not.toBeInTheDocument()
  })
})
