import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '../../__tests__/test-utils'
import type { VehicleStatistics } from '../../types/dashboard'

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>()
  return { ...actual, useNavigate: () => mockNavigate }
})
vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({ user: null, isAuthenticated: false }),
}))
// The LiveLink widget fetches on mount — make it render nothing (no device).
vi.mock('@/services/livelinkService', () => ({
  livelinkService: {
    getVehicleStatus: vi.fn().mockRejectedValue(new Error('no device')),
  },
}))

import VehicleStatisticsCard from '../VehicleStatisticsCard'

const STATS: VehicleStatistics = {
  vin: '1HGBH41JXMN109186',
  year: 2021,
  make: 'Ford',
  model: 'F-150',
  vehicle_type: 'FifthWheel',
  main_photo_url: null,
  usage_unit: 'distance',
  current_hours: null,
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
}

describe('VehicleStatisticsCard', () => {
  beforeEach(() => vi.clearAllMocks())

  it('renders the translated vehicle-type label, never the raw enum value', () => {
    render(<VehicleStatisticsCard stats={STATS} />)
    // Mapped through vehicleTypeLabels.* -> the key under the vitest i18n mock,
    // proving raw 'FifthWheel' is never shown to the user.
    expect(screen.getByText('vehicleTypeLabels.FifthWheel')).toBeInTheDocument()
    expect(screen.queryByText('FifthWheel')).not.toBeInTheDocument()
  })

  it('navigates to the vehicle via the whole-card stretched-link button', () => {
    render(<VehicleStatisticsCard stats={STATS} />)
    fireEvent.click(
      screen.getByRole('button', { name: /vehicleStatisticsCardExtra\.viewDetails/ }),
    )
    expect(mockNavigate).toHaveBeenCalledWith('/vehicles/1HGBH41JXMN109186')
  })

  it('shows the odometer row and MPG strip for a distance-tracked vehicle', () => {
    render(
      <VehicleStatisticsCard
        stats={{
          ...STATS,
          usage_unit: 'distance',
          total_odometer_records: 1,
          latest_odometer_km: '5000',
          average_l_per_100km: '8.5',
        }}
      />
    )
    expect(screen.getByText('vehicleStats.latestOdometer')).toBeInTheDocument()
    expect(screen.queryByText('vehicleStats.latestHours')).not.toBeInTheDocument()
    expect(screen.getByText(/vehicleStatisticsCardExtra\.averageFuelEconomy/)).toBeInTheDocument()
  })

  it('shows Latest Hours and hides odometer + MPG for an hour-metered vehicle', () => {
    render(
      <VehicleStatisticsCard
        stats={{
          ...STATS,
          vehicle_type: 'ATV',
          usage_unit: 'hours',
          current_hours: '123.5',
          // Present in the data but must be IGNORED when tracking hours:
          latest_odometer_km: '5000',
          average_l_per_100km: '8.5',
        }}
      />
    )
    expect(screen.getByText('vehicleStats.latestHours')).toBeInTheDocument()
    expect(screen.queryByText('vehicleStats.latestOdometer')).not.toBeInTheDocument()
    // Distance-based MPG strip is hidden for hour vehicles.
    expect(
      screen.queryByText(/vehicleStatisticsCardExtra\.averageFuelEconomy/)
    ).not.toBeInTheDocument()
  })
})
