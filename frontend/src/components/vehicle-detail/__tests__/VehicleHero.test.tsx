import { describe, it, expect, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { render, screen } from '../../../__tests__/test-utils'
import type { Vehicle, VehicleDetailStats } from '../../../types/vehicle'
import { IMPERIAL_UNITS } from '../../../__tests__/factories'
import { makeUnitFormat } from '../../../utils/unitFormat'

vi.mock('../../../hooks/useUnitPreference', () => ({
  useUnitPreference: () => ({
    system: 'imperial',
    showBoth: false,
    gallonStandard: 'us',
    // The RESOLVED set, not just the collapsed system: this component reads
    // its distance through `useUnitFormat()`, which closes over `units`.
    units: IMPERIAL_UNITS,
  }),
}))

// LOCAL i18n mock (same pattern as FuelRecordList's B7 fix): the GLOBAL
// setup.ts mock is `t: (key) => key`, which discards interpolation args, so
// `t('vehicleStats.hoursValue', { value })` renders the identical string
// regardless of value — a test proving latest_hours (not the stale
// current_hours column) drives the display needs the value to come through.
// This override retains `options.value` and is otherwise behaviour-identical
// to the global mock (bare key) so the pre-existing tests below stay green.
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: { value?: unknown }) =>
      options?.value != null ? `${key} (${options.value})` : key,
    i18n: { language: 'en', changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children: React.ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: () => {} },
}))

import VehicleHero from '../VehicleHero'

const VEHICLE = {
  vin: 'TEST12345678901234', nickname: 'Test Car', vehicle_type: 'Car',
  year: 2024, make: 'Toyota', model: 'Camry', archived_visible: true,
} as Vehicle

const STATS: VehicleDetailStats = {
  overdue_count: 3, upcoming_count: 2,
  usage_unit: 'distance', current_hours: null,
  latest_hours: null, average_l_per_hr: null, average_cost_per_hr: null,
  secondary_usage_enabled: false,
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
    const expected = makeUnitFormat(IMPERIAL_UNITS).distance.formatPrimary(
      parseFloat(STATS.latest_odometer_km!)
    )
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

  it('shows the hero reading from latest_hours, NOT the stale current_hours column (fixture where the two differ)', () => {
    const hoursStats: VehicleDetailStats = {
      ...STATS,
      usage_unit: 'hours',
      current_hours: '999.9', // decoy stale column — must be ignored
      latest_hours: '55.5',
    }
    render(<VehicleHero vehicle={VEHICLE} photoUrl={null} fromCache={false} detailStats={hoursStats} />)
    expect(screen.getByText('detail.misc.hours')).toBeInTheDocument()
    expect(screen.getByText('vehicleStats.hoursValue (55.5)')).toBeInTheDocument()
    expect(screen.queryByText('vehicleStats.hoursValue (999.9)')).not.toBeInTheDocument()
    // Pure-hours: no odometer reading chip.
    expect(screen.queryByText('detail.misc.odometer')).not.toBeInTheDocument()
  })

  it('dual-tracking (distance primary) shows BOTH the odometer AND the hours reading', () => {
    const dualStats: VehicleDetailStats = {
      ...STATS,
      usage_unit: 'distance',
      secondary_usage_enabled: true,
      latest_odometer_km: '160000.00',
      latest_hours: '321.75',
    }
    render(<VehicleHero vehicle={VEHICLE} photoUrl={null} fromCache={false} detailStats={dualStats} />)
    const expectedDistance = makeUnitFormat(IMPERIAL_UNITS).distance.formatPrimary(
      parseFloat(dualStats.latest_odometer_km!)
    )
    expect(screen.getByText('detail.misc.odometer')).toBeInTheDocument()
    expect(screen.getByText(expectedDistance)).toBeInTheDocument()
    expect(screen.getByText('detail.misc.hours')).toBeInTheDocument()
    expect(screen.getByText('vehicleStats.hoursValue (321.75)')).toBeInTheDocument()
  })

  it('dual-tracking (hours primary) shows BOTH the hours AND the odometer reading', () => {
    const dualStats: VehicleDetailStats = {
      ...STATS,
      usage_unit: 'hours',
      secondary_usage_enabled: true,
      latest_odometer_km: '160000.00',
      latest_hours: '321.75',
    }
    render(<VehicleHero vehicle={VEHICLE} photoUrl={null} fromCache={false} detailStats={dualStats} />)
    const expectedDistance = makeUnitFormat(IMPERIAL_UNITS).distance.formatPrimary(
      parseFloat(dualStats.latest_odometer_km!)
    )
    expect(screen.getByText('detail.misc.hours')).toBeInTheDocument()
    expect(screen.getByText('vehicleStats.hoursValue (321.75)')).toBeInTheDocument()
    expect(screen.getByText('detail.misc.odometer')).toBeInTheDocument()
    expect(screen.getByText(expectedDistance)).toBeInTheDocument()
  })

  it('never reads detailStats.current_hours (grep-style source check — the stale column is retired)', () => {
    const src = readFileSync(resolve(__dirname, '../VehicleHero.tsx'), 'utf8')
    expect(src).not.toMatch(/current_hours/)
  })
})
