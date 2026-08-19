import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '../../__tests__/test-utils'

const mockGet = vi.fn()
vi.mock('../../services/api', () => ({
  default: { get: (...args: unknown[]) => mockGet(...args) },
}))

vi.mock('../../services/externalVehicleService', () => ({
  listExternalVehicles: vi.fn().mockResolvedValue({ vehicles: [], total: 0 }),
}))

vi.mock('../../components/VehicleStatisticsCard', () => ({
  default: ({
    stats,
  }: {
    stats: { year: number | null; make: string | null; model: string | null }
  }) => <div data-testid="vehicle-card">{`${stats.year} ${stats.make} ${stats.model}`}</div>,
}))
vi.mock('../../components/VehicleWizard', () => ({ default: () => null }))
vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({ user: null, isAuthenticated: false }),
}))

import Dashboard from '../Dashboard'

function vehicle(v: {
  vin: string
  year: number
  make: string
  model: string
  is_shared_with_me?: boolean
}): Record<string, unknown> {
  return {
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
    ...v,
  }
}

function dashboardPayload(vehicles: Record<string, unknown>[]): { data: Record<string, unknown> } {
  return {
    data: {
      total_vehicles: vehicles.length,
      vehicles,
      multi_user_enabled: false,
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
}

function settingsPayload(flags: {
  familyFriends?: boolean
}): { data: { settings: { key: string; value: string }[] } } {
  return {
    data: {
      settings: [
        {
          key: 'family_friends_enabled',
          value: flags.familyFriends ? 'true' : 'false',
        },
      ],
    },
  }
}

function mockDashboard(
  vehicles: Record<string, unknown>[],
  flags: { familyFriends?: boolean } = {
    familyFriends: true,
  },
) {
  mockGet.mockImplementation((url: string) => {
    if (String(url).includes('settings')) {
      return Promise.resolve(settingsPayload(flags))
    }
    return Promise.resolve(dashboardPayload(vehicles))
  })
}

const order = (): string[] =>
  screen.getAllByTestId('vehicle-card').map((el) => el.textContent ?? '')

describe('Dashboard sectioned layout', () => {
  beforeEach(() => vi.clearAllMocks())

  it('re-sorts vehicles when a Sort option is chosen', async () => {
    mockDashboard([
      vehicle({ vin: 'A', year: 2019, make: 'Aston', model: 'X' }),
      vehicle({ vin: 'B', year: 2022, make: 'BMW', model: 'X' }),
      vehicle({ vin: 'C', year: 2020, make: 'Chevy', model: 'X' }),
    ])
    render(<Dashboard />)
    await waitFor(() =>
      expect(order()).toEqual(['2019 Aston X', '2020 Chevy X', '2022 BMW X']),
    )

    fireEvent.click(screen.getByRole('button', { name: 'dashboard.sortVehicles' }))
    fireEvent.click(screen.getByRole('menuitemradio', { name: 'dashboard.newestFirst' }))

    await waitFor(() =>
      expect(order()).toEqual(['2022 BMW X', '2020 Chevy X', '2019 Aston X']),
    )
  })

  it('splits owned and shared vehicles into sections when Family & Friends is enabled', async () => {
    mockDashboard([
      vehicle({ vin: 'OWN', year: 2021, make: 'Owned', model: 'Y' }),
      vehicle({ vin: 'SHR', year: 2021, make: 'Shared', model: 'Y', is_shared_with_me: true }),
    ])
    render(<Dashboard />)

    await waitFor(() => expect(order()).toHaveLength(2))
    expect(screen.getByText('dashboard.myVehiclesSection')).toBeInTheDocument()
    expect(screen.getByText('dashboard.familyFriendsSection')).toBeInTheDocument()
  })

  it('shows family empty state when nothing is shared or referenced', async () => {
    mockDashboard([vehicle({ vin: 'OWN', year: 2021, make: 'Owned', model: 'Y' })])
    render(<Dashboard />)

    await waitFor(() =>
      expect(screen.getByText('dashboard.familyEmptyTitle')).toBeInTheDocument(),
    )
  })

  it('hides Family & Friends and shared vehicles when the setting is off', async () => {
    mockDashboard(
      [
        vehicle({ vin: 'OWN', year: 2021, make: 'Owned', model: 'Y' }),
        vehicle({ vin: 'SHR', year: 2021, make: 'Shared', model: 'Y', is_shared_with_me: true }),
      ],
      { familyFriends: false },
    )
    render(<Dashboard />)

    await waitFor(() => expect(order()).toEqual(['2021 Owned Y']))
    expect(screen.queryByText('dashboard.familyFriendsSection')).not.toBeInTheDocument()
    expect(screen.queryByText('2021 Shared Y')).not.toBeInTheDocument()
  })
})
