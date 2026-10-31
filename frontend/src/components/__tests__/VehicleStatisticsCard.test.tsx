import { describe, it, expect, vi, beforeEach } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { render, screen, fireEvent } from '../../__tests__/test-utils'
import type { VehicleStatistics } from '../../types/dashboard'
import { makeUser, makeUnitSet, IMPERIAL_UNITS, type User, makeVehicleStatistics } from '../../__tests__/factories'
import { formatFuelRate, formatVolumeRate } from '../../utils/unitFormat'

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

const STATS: VehicleStatistics = makeVehicleStatistics({
  vin: '1HGBH41JXMN109186',
  year: 2021,
  make: 'Ford',
  model: 'F-150',
  vehicle_type: 'FifthWheel',
  archived_visible: false,
})

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

  it('labels a type the app does not recognise Unknown instead of dropping the badge', () => {
    // The dashboard row the API sends for a stored type this version doesn't know.
    render(<VehicleStatisticsCard stats={makeVehicleStatistics({ vehicle_type: null })} />)

    expect(screen.getByText('common:unknown')).toBeInTheDocument()
    expect(screen.queryByText(/vehicleTypeLabels\./)).not.toBeInTheDocument()
  })

  it('navigates to the vehicle via the whole-card stretched-link button', () => {
    render(<VehicleStatisticsCard stats={STATS} />)
    fireEvent.click(
      screen.getByRole('button', { name: /vehicleStatisticsCardExtra\.viewDetails/ }),
    )
    expect(mockNavigate).toHaveBeenCalledWith('/vehicles/1HGBH41JXMN109186')
  })

  describe('the VIN stays selectable (#179)', () => {
    // ★ WHAT THESE CANNOT COVER. The fix has two halves and only one is
    // testable here. Removing `pointer-events-none` is structural and the first
    // case below catches it. The `z-10` that lifts this text above the footer
    // button's stretched `after:inset-0` is pure STACKING, and jsdom has no
    // layout and no stacking contexts: deleting `z-10` leaves every test in
    // this file green while the card goes right back to being unselectable in a
    // browser. Verified by mutation, not assumed. That half is only ever
    // confirmed on a real device, so do not read these three passing as proof
    // the VIN can be highlighted.
    const vinOf = (vin: string) => screen.getByText(vin)

    it('has no ancestor that disables pointer events', () => {
      // jsdom applies no CSS, so this asserts the structural cause rather than
      // a computed style. `pointer-events-none` does not merely pass clicks
      // through: text under it cannot receive a selection at all.
      render(<VehicleStatisticsCard stats={STATS} />)
      let node: HTMLElement | null = vinOf(STATS.vin)
      const blocking: string[] = []
      while (node) {
        if (String(node.className || '').includes('pointer-events-none')) {
          blocking.push(String(node.className))
        }
        node = node.parentElement
      }
      expect(blocking).toEqual([])
    })

    it('still navigates when the VIN itself is clicked', () => {
      // The whole card is one nav target via the footer button's stretched
      // `after:inset-0`. Lifting the text above that pseudo-element is what
      // makes it selectable, so the text has to carry the navigation itself or
      // clicking the title would quietly stop working.
      render(<VehicleStatisticsCard stats={STATS} />)
      fireEvent.click(vinOf(STATS.vin))
      expect(mockNavigate).toHaveBeenCalledWith(`/vehicles/${STATS.vin}`)
    })

    it('does not navigate on the click that ends a selection', () => {
      render(<VehicleStatisticsCard stats={STATS} />)
      const spy = vi.spyOn(window, 'getSelection').mockReturnValue({
        isCollapsed: false,
        toString: () => STATS.vin,
      } as unknown as Selection)

      fireEvent.click(vinOf(STATS.vin))

      expect(mockNavigate).not.toHaveBeenCalled()
      spy.mockRestore()
    })
  })

  describe('towing (#181)', () => {
    const distance = {
      usage_unit: 'distance' as const,
      total_odometer_records: 1,
      latest_odometer_km: '5000',
    }

    it('headlines the figure without towing, says so, and shows towing alone beneath', () => {
      render(
        <VehicleStatisticsCard
          stats={{
            ...STATS,
            ...distance,
            average_l_per_100km: '8.00',
            towing_l_per_100km: '16.00',
          }}
        />
      )
      // 235.2145833/8 = 29.4 and /16 = 14.7, at the mpg_us adapter's one
      // decimal. The second line is the towing tanks ALONE, so it can say
      // "Towing"; the headline says "not towing" only because this vehicle tows.
      expect(screen.getByText('29.4 MPG')).toBeInTheDocument()
      expect(screen.getByText('vehicleStatisticsCardExtra.averageFuelEconomyNotTowing (MPG)')).toBeInTheDocument()
      expect(screen.getByText('vehicleStats.towing: 14.7 MPG')).toBeInTheDocument()
    })

    it('shows no towing line, and no qualifier, for a vehicle that never tows', () => {
      // This is the "not to clutter the display of vehicles that don't tow"
      // half of the request, and it is the case almost every vehicle is in.
      render(
        <VehicleStatisticsCard
          stats={{
            ...STATS,
            ...distance,
            average_l_per_100km: '8.00',
            towing_l_per_100km: null,
          }}
        />
      )
      expect(screen.getByText('29.4 MPG')).toBeInTheDocument()
      expect(screen.getByText('vehicleStatisticsCardExtra.averageFuelEconomy (MPG)')).toBeInTheDocument()
      expect(screen.queryByText(/vehicleStats\.towing:/)).not.toBeInTheDocument()
      expect(screen.queryByText(/NotTowing/)).not.toBeInTheDocument()
    })

    it('labels the figure when every fill-up was towing', () => {
      // No non-towing figure exists. Showing nothing would hide a number the
      // vehicle really has, so the towing one headlines AND says so, once.
      render(
        <VehicleStatisticsCard
          stats={{
            ...STATS,
            ...distance,
            average_l_per_100km: null,
            towing_l_per_100km: '10.00',
          }}
        />
      )
      expect(screen.getByText('23.5 MPG')).toBeInTheDocument()
      expect(screen.getByText('vehicleStats.towingAll')).toBeInTheDocument()
      expect(screen.queryByText(/vehicleStats\.towing:/)).not.toBeInTheDocument()
      expect(screen.queryByText(/NotTowing/)).not.toBeInTheDocument()
    })
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

    // 5000 / 1.609344 = 3106.86, at the mi adapter's zero decimals.
    expect(screen.getByText('3,107 mi')).toBeInTheDocument()
    // 235.2145833... / 9.4160546 = 24.98, at the mpg_us adapter's one.
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
      screen.getByText('vehicleStatisticsCardExtra.averageFuelEconomy (gal (UK)/hr)'),
    ).toBeInTheDocument()
    expect(screen.getByText('1.00 gal (UK)/hr')).toBeInTheDocument()
    // What the US gallon would have printed: 4.54609 / 3.785411784 = 1.20.
    expect(screen.queryByText('1.20 gal/hr')).not.toBeInTheDocument()
  })

  it('★ the "Last 3 tanks:" line reads the same token as the average above it', () => {
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
    expect(screen.getByText('vehicleStats.lastTanks: 7.50 L/100km')).toBeInTheDocument()
    // 7.5 L through the gal_us adapter, which is what the volume formatter
    // would have rendered here.
    expect(screen.queryByText(/1\.98 gal/)).not.toBeInTheDocument()
  })

  it('never reads stats.current_hours (grep-style source check — the stale column is retired)', () => {
    const src = readFileSync(resolve(__dirname, '../VehicleStatisticsCard.tsx'), 'utf8')
    expect(src).not.toMatch(/current_hours/)
  })

  describe('the photo badge flags what needs attention', () => {
    it('shows the due-soon count, not the pending count', () => {
      render(
        <VehicleStatisticsCard
          stats={{ ...STATS, upcoming_maintenance_count: 3, due_soon_maintenance_count: 1 }}
        />,
      )
      expect(screen.getByText('vehicleStats.dueSoon')).toBeInTheDocument()
      expect(screen.queryByText('vehicleStats.upcoming')).not.toBeInTheDocument()
    })

    it('shows no badge when nothing is overdue or due soon, however many are pending', () => {
      render(
        <VehicleStatisticsCard
          stats={{ ...STATS, upcoming_maintenance_count: 3, due_soon_maintenance_count: 0 }}
        />,
      )
      expect(screen.queryByText('vehicleStats.dueSoon')).not.toBeInTheDocument()
    })

    it('lets overdue win over due soon', () => {
      render(
        <VehicleStatisticsCard
          stats={{ ...STATS, overdue_maintenance_count: 1, due_soon_maintenance_count: 2 }}
        />,
      )
      expect(screen.getByText('vehicleStats.overdue')).toBeInTheDocument()
      expect(screen.queryByText('vehicleStats.dueSoon')).not.toBeInTheDocument()
    })
  })
})

describe('towable RV rows (fifth wheels and travel trailers only)', () => {
  const towVehicle = { vin: '3C63R3PL1SG545506', year: 2025, make: 'RAM', model: '3500' }
  const propane = { propane_l_per_month: '20.8', recent_propane_l_per_month: '5.7' }

  beforeEach(() => {
    vi.clearAllMocks()
    auth.user = null
  })

  it('a fifth wheel lists its tow vehicle by year make model', () => {
    render(<VehicleStatisticsCard stats={{ ...STATS, tow_vehicle: towVehicle }} />)
    expect(screen.getByText('vehicleStats.towedBy')).toBeInTheDocument()
    expect(screen.getByText('2025 RAM 3500')).toBeInTheDocument()
  })

  it('a travel trailer shows average propane per month in the reader\'s volume unit, with the recent line', () => {
    render(<VehicleStatisticsCard stats={{ ...STATS, vehicle_type: 'TravelTrailer', ...propane }} />)
    // The anonymous client resolves to the imperial preset, so litres render as gallons.
    const gal = formatVolumeRate(IMPERIAL_UNITS, 20.8, '/mo')
    expect(gal).toMatch(/gal\/mo$/)
    expect(screen.getByText('vehicleStats.averagePropane')).toBeInTheDocument()
    expect(screen.getByText(gal)).toBeInTheDocument()
    expect(screen.getByText(/vehicleStats\.lastRefills/)).toBeInTheDocument()
  })

  it('a rate from a single window has no recent line', () => {
    render(
      <VehicleStatisticsCard
        stats={{ ...STATS, propane_l_per_month: '20.8', recent_propane_l_per_month: '20.8' }}
      />,
    )
    expect(screen.getByText('vehicleStats.averagePropane')).toBeInTheDocument()
    expect(screen.queryByText(/vehicleStats\.lastRefills/)).not.toBeInTheDocument()
  })

  it('a car with the same fields shows neither row', () => {
    render(
      <VehicleStatisticsCard stats={{ ...STATS, vehicle_type: 'Car', tow_vehicle: towVehicle, ...propane }} />,
    )
    expect(screen.queryByText('vehicleStats.towedBy')).not.toBeInTheDocument()
    expect(screen.queryByText('vehicleStats.averagePropane')).not.toBeInTheDocument()
  })
})
