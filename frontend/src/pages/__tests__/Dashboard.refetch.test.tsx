/**
 * Pins the `location.key` dependency in Dashboard's load effect: navigating
 * to the dashboard route while ALREADY on it (nav link click) changes only
 * the location key, not the mount, and must still refetch. Without it a
 * snooze or completion made on a detail page shows stale fleet counts when
 * the user returns through the nav.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import { renderWithQueryClient } from '@/__tests__/queryClient'
import { fireEvent } from '@testing-library/react'
import { Link, MemoryRouter, Route, Routes } from 'react-router-dom'

const mockGet = vi.fn()
vi.mock('../../services/api', () => ({
  default: { get: (...args: unknown[]) => mockGet(...args) },
}))
vi.mock('../../services/externalVehicleService', () => ({
  listExternalVehicles: vi.fn().mockResolvedValue({ vehicles: [], total: 0 }),
}))
vi.mock('../../components/VehicleStatisticsCard', () => ({
  default: () => <div data-testid="vehicle-card" />,
}))
vi.mock('../../components/VehicleWizard', () => ({ default: () => null }))
vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({ user: null, isAuthenticated: false }),
}))

import Dashboard from '../Dashboard'

beforeEach(() => {
  vi.clearAllMocks()
  mockGet.mockImplementation((url: string) => {
    if (String(url).includes('settings')) {
      return Promise.resolve({ data: { settings: [] } })
    }
    return Promise.resolve({
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
        fleet_health: {
          overdue_count: 0,
          upcoming_30d_count: 0,
          year: 2026,
          spent_this_year: '0.00',
          next_due: null,
        },
      },
    })
  })
})

const dashboardCalls = (): number =>
  mockGet.mock.calls.filter(([url]) => String(url).includes('/dashboard')).length

describe('Dashboard refetch on same-route navigation', () => {
  it('a nav click back to the dashboard route refetches without a remount', async () => {
    renderWithQueryClient(
      <MemoryRouter initialEntries={['/']}>
        <Link to="/">go home</Link>
        <Routes>
          <Route path="/" element={<Dashboard />} />
        </Routes>
      </MemoryRouter>,
    )
    await waitFor(() => expect(dashboardCalls()).toBe(1))
    fireEvent.click(screen.getByText('go home'))
    await waitFor(() => expect(dashboardCalls()).toBe(2))
  })
})
