import { describe, it, expect, vi, beforeEach } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { render, screen, fireEvent } from '../../__tests__/test-utils'
import type { VehicleStatistics } from '../../types/dashboard'
import { makeUser, makeUnitSet, IMPERIAL_UNITS, type User } from '../../__tests__/factories'
import { formatFuelRate } from '../../utils/unitFormat'

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>()
  return { ...actual, useNavigate: () => mockNavigate }
})
// Hoisted so a test can put an account with CUSTOM resolved units behind
// `useUnitPreference`'s rung 1. Every test that does not set it renders as the
// anonymous client the rest of this file has always assumed: rung 4, the
// imperial preset.
const auth = vi.hoisted(() => ({ user: null as User | null }))
vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({
    user: auth.user,
    isAuthenticated: auth.user !== null,
    defaultUnitPrefs: null,
  }),
}))
// The LiveLink widget fetches on mount — make it render nothing (no device).
vi.mock('@/services/livelinkService', () => ({
  livelinkService: {
    getVehicleStatus: vi.fn().mockRejectedValue(new Error('no device')),
  },
}))
// LOCAL i18n mock (same pattern as FuelRecordList's B7 fix): the GLOBAL
// setup.ts mock is `t: (key) => key`, which discards interpolation args, so
// `t('vehicleStats.hoursValue', { value })` / `t('...averageFuelEconomy', { unit })`
// render the identical string regardless of the option — tests below need the
// value/unit to come through to prove latest_hours (not the stale current_hours
// column) drives the display, and to tell the consumption strip from the
// fuel-rate strip.
// Otherwise behaviour-identical to the global mock (bare key), so the
// pre-existing tests stay green.
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: { value?: unknown; unit?: string }) => {
      if (options?.value != null) return `${key} (${options.value})`
      if (options?.unit) return `${key} (${options.unit})`
      return key
    },
    i18n: { language: 'en', changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children: React.ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: () => {} },
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
  latest_hours: null,
  average_l_per_hr: null,
  average_cost_per_hr: null,
  secondary_usage_enabled: false,
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
  beforeEach(() => {
    vi.clearAllMocks()
    auth.user = null
  })

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
    expect(screen.getByText('vehicleStatisticsCardExtra.averageFuelEconomy (MPG)')).toBeInTheDocument()
  })

  it('shows Latest Hours from latest_hours (NOT the stale current_hours column) + fuel-rate economy, hides odometer + MPG for a pure-hours vehicle', () => {
    render(
      <VehicleStatisticsCard
        stats={{
          ...STATS,
          vehicle_type: 'ATV',
          usage_unit: 'hours',
          current_hours: '999.9', // decoy stale column — must be ignored
          latest_hours: '123.5',
          average_l_per_hr: '0.95',
          // Present in the data but must be IGNORED when tracking hours only:
          latest_odometer_km: '5000',
          average_l_per_100km: '8.5',
        }}
      />
    )
    expect(screen.getByText('vehicleStats.latestHours')).toBeInTheDocument()
    expect(screen.getByText('vehicleStats.hoursValue (123.5)')).toBeInTheDocument()
    expect(screen.queryByText('vehicleStats.hoursValue (999.9)')).not.toBeInTheDocument()
    expect(screen.queryByText('vehicleStats.latestOdometer')).not.toBeInTheDocument()
    // Distance-based MPG strip is hidden for hour vehicles; the rate shown instead.
    expect(screen.queryByText('vehicleStatisticsCardExtra.averageFuelEconomy (MPG)')).not.toBeInTheDocument()
    const expectedRate = formatFuelRate(IMPERIAL_UNITS, 0.95)
    expect(screen.getByText('vehicleStatisticsCardExtra.averageFuelEconomy (gal/hr)')).toBeInTheDocument()
    expect(screen.getByText(expectedRate)).toBeInTheDocument()
  })

  it('dual-tracking vehicle shows BOTH distance + hours activity rows and BOTH economy strips', () => {
    render(
      <VehicleStatisticsCard
        stats={{
          ...STATS,
          usage_unit: 'distance',
          secondary_usage_enabled: true,
          total_odometer_records: 1,
          latest_odometer_km: '5000',
          latest_hours: '321.75',
          average_l_per_100km: '8.5',
          average_l_per_hr: '0.95',
        }}
      />
    )
    expect(screen.getByText('vehicleStats.latestOdometer')).toBeInTheDocument()
    expect(screen.getByText('vehicleStats.latestHours')).toBeInTheDocument()
    expect(screen.getByText('vehicleStats.hoursValue (321.75)')).toBeInTheDocument()
    expect(screen.getByText('vehicleStatisticsCardExtra.averageFuelEconomy (MPG)')).toBeInTheDocument()
    expect(screen.getByText('vehicleStatisticsCardExtra.averageFuelEconomy (gal/hr)')).toBeInTheDocument()
  })

  it('★ one card, one unit system: the economy strip follows the same account as the odometer row', () => {
    // The defect this test exists for. Task 6 moved the odometer onto
    // `u.distance` and left consumption on `formatFuelEconomy(l, system)`,
    // where `system` is collapsed from VOLUME (spec D8). So this account, which
    // chose litres, miles and MPG, read `3,107 mi` directly above `9.4
    // L/100km`: two unit systems as adjacent rows of one card, neither reading
    // wrong on its own.
    auth.user = makeUser({
      unit_preference: 'custom',
      resolved_units: makeUnitSet({ distance: 'mi', consumption: 'mpg_us' }),
    })

    render(
      <VehicleStatisticsCard
        stats={{
          ...STATS,
          usage_unit: 'distance',
          total_odometer_records: 1,
          latest_odometer_km: '5000',
          average_l_per_100km: '9.4160546',
        }}
      />
    )

    // 5000 / 1.60934 = 3106.86, at the mi adapter's zero decimals.
    expect(screen.getByText('3,107 mi')).toBeInTheDocument()
    // 235.214 / 9.4160546 = 24.98, at the mpg_us adapter's one.
    expect(screen.getByText('vehicleStatisticsCardExtra.averageFuelEconomy (MPG)')).toBeInTheDocument()
    expect(screen.getByText('25.0 MPG')).toBeInTheDocument()
    expect(screen.queryByText('9.4 L/100km')).not.toBeInTheDocument()
  })

  it('★ and the mirror: a gallons-and-L/100km account reads L/100km', () => {
    // Without this, the assertion above is satisfied by anything that always
    // answers MPG, which is what the imperial leg of the retired formatter did.
    auth.user = makeUser({
      unit_preference: 'custom',
      resolved_units: { ...IMPERIAL_UNITS, consumption: 'l_100km' },
    })

    render(
      <VehicleStatisticsCard
        stats={{ ...STATS, usage_unit: 'distance', average_l_per_100km: '9.4160546' }}
      />
    )

    expect(
      screen.getByText('vehicleStatisticsCardExtra.averageFuelEconomy (L/100km)'),
    ).toBeInTheDocument()
    expect(screen.getByText('9.42 L/100km')).toBeInTheDocument()
    expect(screen.queryByText('25.0 MPG')).not.toBeInTheDocument()
  })

  it('★ the fuel-rate strip names the account\'s own gallon, not the instance\'s', () => {
    // `UnitFormatter.formatFuelRate` divided by a MUTABLE static following the
    // INSTANCE gallon setting, so this UK account read 4.54609 L/hr as
    // "1.20 GPH" while its volume column already called the same quantity one
    // imperial gallon.
    auth.user = makeUser({
      unit_preference: 'custom',
      resolved_units: { ...IMPERIAL_UNITS, volume: 'gal_uk', secondary_gallon: 'uk' },
    })

    render(
      <VehicleStatisticsCard
        stats={{
          ...STATS,
          vehicle_type: 'ATV',
          usage_unit: 'hours',
          latest_hours: '123.5',
          average_l_per_hr: '4.54609',
        }}
      />
    )

    expect(
      screen.getByText('vehicleStatisticsCardExtra.averageFuelEconomy (gal/hr)'),
    ).toBeInTheDocument()
    expect(screen.getByText('1.00 gal/hr')).toBeInTheDocument()
    expect(screen.queryByText('1.20 gal/hr')).not.toBeInTheDocument()
  })

  it('★ the "Recent:" line reads the same token as the average above it', () => {
    // ★ THIS LINE WAS EXECUTED BY NO TEST AT ALL until fix round 1: every
    // fixture in the repo sets `recent_l_per_100km: null`, and a fixture that
    // nulls a value cannot exercise the renderer that reads it. It is one of
    // task 6b's 31 migrated sites, it sits three lines below the average the
    // mutation table did pin, and rerouting it to `u.volume` compiled clean and
    // left the whole suite green.
    //
    // It also needs a value DIFFERENT from the average, because the card hides
    // the line when the two agree.
    auth.user = makeUser({
      unit_preference: 'custom',
      resolved_units: { ...IMPERIAL_UNITS, consumption: 'l_100km' },
    })

    render(
      <VehicleStatisticsCard
        stats={{
          ...STATS,
          usage_unit: 'distance',
          average_l_per_100km: '9.4160546',
          recent_l_per_100km: '7.5',
        }}
      />
    )

    expect(screen.getByText('9.42 L/100km')).toBeInTheDocument()
    expect(screen.getByText('vehicleStats.recent: 7.50 L/100km')).toBeInTheDocument()
    // 7.5 L through the gal_us adapter, which is what the volume formatter
    // would have rendered here.
    expect(screen.queryByText(/1\.98 gal/)).not.toBeInTheDocument()
  })

  it('never reads stats.current_hours (grep-style source check — the stale column is retired)', () => {
    const src = readFileSync(resolve(__dirname, '../VehicleStatisticsCard.tsx'), 'utf8')
    expect(src).not.toMatch(/current_hours/)
  })
})
