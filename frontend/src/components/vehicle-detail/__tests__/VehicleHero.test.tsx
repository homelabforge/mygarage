import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '../../../__tests__/test-utils'
import type { Vehicle, VehicleDetailStats } from '../../../types/vehicle'
import { UnitFormatter } from '../../../utils/units'

vi.mock('../../../hooks/useUnitPreference', () => ({
  useUnitPreference: () => ({ system: 'imperial' }),
}))

import VehicleHero from '../VehicleHero'

const VEHICLE = {
  vin: 'TEST12345678901234', nickname: 'Test Car', vehicle_type: 'Car',
  year: 2024, make: 'Toyota', model: 'Camry', archived_visible: true,
} as Vehicle

const STATS: VehicleDetailStats = {
  overdue_count: 3, upcoming_count: 2,
  usage_unit: 'distance', current_hours: null,
  latest_odometer_km: '160000.00', latest_odometer_date: '2026-07-01',
  last_service_date: '2026-06-15', last_fillup_date: '2026-07-10',
  spent_this_year: '1234.50', year: 2026,
}

describe('VehicleHero', () => {
  it('renders name / ymm / VIN and NO reading or badge when stats are null', () => {
    render(<VehicleHero vehicle={VEHICLE} photoUrl={null} fromCache={false} detailStats={null} />)
    expect(screen.getByRole('heading', { name: 'Test Car' })).toBeInTheDocument()
    expect(screen.getByText('2024 Toyota Camry')).toBeInTheDocument()
    expect(screen.getByText('TEST12345678901234')).toBeInTheDocument()
    expect(screen.queryByText('detail.misc.odometer')).not.toBeInTheDocument()
    expect(screen.queryByText('vehicleStats.overdue')).not.toBeInTheDocument()
    expect(screen.queryByText('vehicleStats.upcoming')).not.toBeInTheDocument()
  })

  it('renders the overdue badge + boundary-converted odometer + reading date from nonzero stats', () => {
    render(<VehicleHero vehicle={VEHICLE} photoUrl={null} fromCache={false} detailStats={STATS} />)
    expect(screen.getByText('vehicleStats.overdue')).toBeInTheDocument()   // overdue wins (3 > 0)
    expect(screen.queryByText('vehicleStats.upcoming')).not.toBeInTheDocument()
    expect(screen.getByText('detail.misc.odometer')).toBeInTheDocument()
    // The km is converted at the boundary (would fail if the hero printed raw km).
    const expected = UnitFormatter.formatDistance(parseFloat(STATS.latest_odometer_km!), 'imperial')
    expect(screen.getByText(expected)).toBeInTheDocument()
    // Companion reading date is displayed (m2); only the reading date carries 2026 here.
    expect(screen.getByText(/2026/)).toBeInTheDocument()
  })

  it('shows the upcoming badge when nothing is overdue', () => {
    render(<VehicleHero vehicle={VEHICLE} photoUrl={null} fromCache={false}
      detailStats={{ ...STATS, overdue_count: 0, upcoming_count: 2 }} />)
    expect(screen.getByText('vehicleStats.upcoming')).toBeInTheDocument()
    expect(screen.queryByText('vehicleStats.overdue')).not.toBeInTheDocument()
  })

  it('omits the odometer reading for a non-motorized vehicle even with stats', () => {
    render(<VehicleHero vehicle={{ ...VEHICLE, vehicle_type: 'FifthWheel' } as Vehicle}
      photoUrl={null} fromCache={false} detailStats={STATS} />)
    expect(screen.queryByText('detail.misc.odometer')).not.toBeInTheDocument()
  })
})
