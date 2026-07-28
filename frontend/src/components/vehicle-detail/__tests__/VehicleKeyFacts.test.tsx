import { describe, it, expect, vi } from 'vitest'
import { render, screen, within } from '../../../__tests__/test-utils'
import type { VehicleDetailStats } from '../../../types/vehicle'

vi.mock('../../../contexts/AuthContext', () => ({
  useAuth: () => ({ user: null, isAuthenticated: false }),
}))

import VehicleKeyFacts from '../VehicleKeyFacts'

const STATS: VehicleDetailStats = {
  overdue_count: 3,
  upcoming_count: 2,
  usage_unit: 'distance',
  current_hours: null,
  latest_odometer_km: '160000.00',
  latest_odometer_date: '2026-07-01',
  last_service_date: '2026-06-15',
  last_fillup_date: '2026-07-10',
  spent_this_year: '1234.50',
  year: 2026,
}

describe('VehicleKeyFacts', () => {
  it('binds each value to its OWN labelled cell (B9 — swap-proof)', () => {
    render(<VehicleKeyFacts stats={STATS} />)
    // Each cell is a role="group" named by its label; bind the value INSIDE it so
    // swapping last_service_date <-> last_fillup_date fails (both dates would
    // otherwise still be in the DOM).
    const service = screen.getByRole('group', { name: 'vehicleStats.lastService' })
    expect(within(service).getByText(/Jun 15, 2026/)).toBeInTheDocument()
    const fillup = screen.getByRole('group', { name: 'vehicleStats.lastFillUp' })
    expect(within(fillup).getByText(/Jul 10, 2026/)).toBeInTheDocument()
    // Spent — real formatCurrency('1234.50') + the year, inside the Spent cell.
    const spent = screen.getByRole('group', { name: 'detail.keyFacts.spent' })
    expect(within(spent).getByText(/1,234\.50/)).toBeInTheDocument()
    expect(within(spent).getByText(/2026/)).toBeInTheDocument()
    // Upcoming reads upcoming_count (2), NOT overdue_count (3) — bound to its cell.
    const upcoming = screen.getByRole('group', { name: 'detail.keyFacts.upcoming' })
    expect(within(upcoming).getByText('2')).toBeInTheDocument()
    expect(within(upcoming).queryByText('3')).not.toBeInTheDocument()
  })

  it('shows the not-specified placeholder in each date cell when dates are null', () => {
    render(<VehicleKeyFacts stats={{ ...STATS, last_service_date: null, last_fillup_date: null }} />)
    const service = screen.getByRole('group', { name: 'vehicleStats.lastService' })
    const fillup = screen.getByRole('group', { name: 'vehicleStats.lastFillUp' })
    expect(within(service).getByText('detail.notSpecified')).toBeInTheDocument()
    expect(within(fillup).getByText('detail.notSpecified')).toBeInTheDocument()
  })
})
