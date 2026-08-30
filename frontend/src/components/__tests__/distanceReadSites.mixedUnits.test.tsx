/**
 * The migrated distance READ sites, driven by a client whose two choices disagree.
 *
 * ★ THE DEFECT THESE ARE THE PROOF OF. `useUnitPreference().system` is
 * D8-collapsed from VOLUME (`useUnitPreference.ts`), so a client resolving
 * `{volume:'L', distance:'mi'}` reads `'metric'` and every one of these
 * components rendered its odometer, its due mileage and its remaining-distance
 * estimate in KILOMETRES to a reader who chose miles. The mirror
 * (`{volume:'gal_us', distance:'km'}`) read miles. Both directions are asserted
 * in every case below, because a fix that merely inverted the branch would
 * satisfy one of them.
 *
 * ★ WHAT THIS FILE COVERS AND WHAT IT DOES NOT, stated because a partial
 * inventory presented as a whole is this workstream's signature failure.
 * Task 6 migrated 27 call sites across 11 files. Eight of those files are
 * mounted here:
 *
 *   FleetHealthStrip, VehicleHero, VehicleStatisticsCard   formatPrimary
 *   OdometerRecordList, WarrantyList, ReminderList,        format + label
 *     ServiceVisitList, DEFRecordList                      + toDisplayText
 *
 * The other three (Analytics, Calendar, FuelRecordList) are page-scale mounts
 * with their own harnesses and use the SAME four call shapes as the eight; they
 * rest on `scripts/enumerate-binary-distance.ts` (zero remaining call sites) and
 * on the units gate, which task 8 made CLEAN-ROOM: `units.baseline.json` is `[]`
 * and any finding fails, so a reintroduction on any of the three fails CI. That
 * is a weaker guarantee than a render, and saying so is the point.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, within } from '@testing-library/react'
import { render } from '../../__tests__/test-utils'
import type { UnitSet } from '@/types/units'
import type { FleetHealth } from '../../types/dashboard'
import type { Vehicle, VehicleDetailStats } from '../../types/vehicle'
import type { WarrantyRecord } from '../../types/warranty'
import type { ServiceVisit } from '../../types/serviceVisit'
import type { Reminder } from '../../types/reminder'
import type { OdometerRecord } from '../../types/odometer'
import type { DEFRecord } from '../../types/def'

/**
 * The resolved set under test, and `system` DERIVED from it.
 *
 * Derived rather than pinned, exactly as `ReminderForm.mixedUnits.test.tsx`
 * argues: a mock that hardcodes `system` cannot express the disagreement these
 * cases exist to catch, because the whole defect is that the real hook computes
 * one from the other.
 */
const unitPrefMock = vi.hoisted(() => ({ units: null as unknown as UnitSet }))
vi.mock('../../hooks/useUnitPreference', async () => {
  const { binarySystemFor } = await import('@/types/units')
  return {
    useUnitPreference: () => ({
      system: binarySystemFor(unitPrefMock.units.volume),
      showBoth: false,
      gallonStandard: unitPrefMock.units.secondary_gallon,
      units: unitPrefMock.units,
    }),
  }
})

// Interpolation-retaining `t`: the global setup.ts mock discards options, so a
// column header carrying `{{unit}}` would render identically for km and mi.
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: { unit?: string }) =>
      options?.unit ? `${key} (${options.unit})` : key,
    i18n: { language: 'en', changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children: React.ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: () => {} },
}))

vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({ user: null, isAuthenticated: false }),
}))
vi.mock('../../hooks/useCurrencyPreference', () => ({
  useCurrencyPreference: () => ({ currencyCode: 'USD', locale: 'en-US', formatCurrency: String }),
}))
vi.mock('../../hooks/useDateLocale', () => ({ useDateLocale: () => 'en-US' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('@tanstack/react-query', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}))
vi.mock('../../services/api', () => ({
  default: { get: vi.fn().mockResolvedValue({ data: { attachments: [] } }) },
}))

vi.mock('../../hooks/queries/useOdometerRecords', () => ({
  useOdometerRecords: () => ({
    data: { records: [ODOMETER_RECORD], latest_odometer_km: '80467' },
    isLoading: false,
    error: null,
  }),
  useDeleteOdometerRecord: () => ({ mutate: vi.fn(), isPending: false, variables: undefined }),
  useImportOdometerCSV: () => ({ mutate: vi.fn(), isPending: false }),
}))
vi.mock('../../hooks/queries/useWarrantyRecords', () => ({
  useWarrantyRecords: () => ({ data: [WARRANTY], isLoading: false, error: null }),
  useDeleteWarrantyRecord: () => ({ mutate: vi.fn(), isPending: false, variables: undefined }),
}))
vi.mock('../../hooks/queries/useServiceVisits', () => ({
  useServiceVisits: () => ({ data: { visits: [VISIT] }, isLoading: false, error: null }),
  useDeleteServiceVisit: () => ({ mutate: vi.fn(), isPending: false, variables: undefined }),
}))
vi.mock('../../hooks/useReminders', () => ({
  useReminders: () => ({ data: [REMINDER], isLoading: false, error: null }),
  useMarkReminderDone: () => ({ mutateAsync: vi.fn() }),
  useMarkReminderDismissed: () => ({ mutateAsync: vi.fn() }),
  useDeleteReminder: () => ({ mutateAsync: vi.fn() }),
}))
vi.mock('../../hooks/useLatestMileage', () => ({ useLatestMileage: () => ({ data: null }) }))
vi.mock('../../hooks/useLatestHours', () => ({ useLatestHours: () => ({ data: null }) }))
vi.mock('../ReminderForm', () => ({ default: () => null }))
vi.mock('../../hooks/queries/useDEFRecords', () => ({
  useDEFRecords: () => ({ data: { records: [DEF_RECORD] }, isLoading: false, error: null }),
  useDEFAnalytics: () => ({ data: DEF_ANALYTICS }),
  useDeleteDEFRecord: () => ({ mutate: vi.fn(), isPending: false, variables: undefined }),
  useCreateDEFRecord: () => ({ mutateAsync: vi.fn() }),
  useUpdateDEFRecord: () => ({ mutateAsync: vi.fn() }),
}))
vi.mock('../livelink/VehicleLiveLinkWidget', () => ({ default: () => null }))
vi.mock('../DEFRecordForm', () => ({ default: () => null }))

import { IMPERIAL_UNITS, METRIC_UNITS } from '../../__tests__/factories'
import FleetHealthStrip from '../FleetHealthStrip'
import VehicleHero from '../vehicle-detail/VehicleHero'
import VehicleStatisticsCard from '../VehicleStatisticsCard'
import OdometerRecordList from '../OdometerRecordList'
import WarrantyList from '../WarrantyList'
import ServiceVisitList from '../ServiceVisitList'
import ReminderList from '../ReminderList'
import DEFRecordList from '../DEFRecordList'

/**
 * 80467 km is EXACTLY 50000 mi (50000 x 1.60934), so both readings are whole
 * numbers and neither can be mistaken for the other by rounding.
 */
const CANONICAL_KM = '80467'
const AS_MILES = '50,000 mi'
const AS_KM = '80,467 km'

/** Litres, but miles. `binarySystemFor('L')` is `'metric'`, so `system` lies. */
const LITRES_MILES: UnitSet = { ...METRIC_UNITS, distance: 'mi', speed: 'mph' }
/** The mirror: gallons, but kilometres. `binarySystemFor('gal_us')` is `'imperial'`. */
const GALLONS_KM: UnitSet = { ...IMPERIAL_UNITS, distance: 'km', speed: 'kmh' }

const ODOMETER_RECORD = {
  id: 1, vin: 'V1', date: '2026-03-01', odometer_km: CANONICAL_KM, notes: 'road trip',
} as unknown as OdometerRecord
const WARRANTY = {
  id: 1, warranty_type: 'Manufacturer', provider: 'Toyota',
  start_date: '2020-01-01', end_date: '2099-12-31',
  mileage_limit_km: CANONICAL_KM, policy_number: 'W-1', coverage_details: '', notes: '',
} as unknown as WarrantyRecord
const VISIT = {
  id: 1, vin: 'V1', date: '2026-03-01', odometer_km: CANONICAL_KM,
  shop_name: 'Shop', total_cost: '40', line_items: [], attachments: [],
} as unknown as ServiceVisit
const REMINDER = {
  id: 1, vin: 'V1', title: 'Oil change', reminder_type: 'mileage',
  due_mileage_km: CANONICAL_KM, due_date: null, is_completed: false, notes: '',
} as unknown as Reminder
const DEF_RECORD = {
  id: 1, vin: 'V1', date: '2026-03-01', odometer_km: CANONICAL_KM,
  liters: '10', cost: '20', entry_type: 'purchase', fill_level: null,
} as unknown as DEFRecord
const DEF_ANALYTICS = {
  record_count: 2, estimated_km_remaining: CANONICAL_KM, estimated_days_remaining: null,
  liters_per_1000_km: '3.4', avg_cost_per_liter: null, total_cost: null, total_liters: null,
  data_confidence: 'high',
}
const FLEET: FleetHealth = {
  overdue_count: 3, upcoming_30d_count: 2, year: 2026, spent_this_year: '1234.50',
  next_due: {
    vin: 'TEST0000000000001', label: 'Oil change soon',
    due_date: '2026-08-01', due_mileage_km: CANONICAL_KM,
  },
}
const VEHICLE = {
  vin: 'TEST12345678901234', nickname: 'Test Car', vehicle_type: 'Car',
  year: 2024, make: 'Toyota', model: 'Camry', archived_visible: true,
} as Vehicle
const HERO_STATS: VehicleDetailStats = {
  overdue_count: 3, upcoming_count: 2,
  usage_unit: 'distance', current_hours: null,
  latest_hours: null, average_l_per_hr: null, average_cost_per_hr: null,
  secondary_usage_enabled: false,
  latest_odometer_km: CANONICAL_KM, latest_odometer_date: '2026-07-01',
  last_service_date: '2026-06-15', last_fillup_date: '2026-07-10',
  spent_this_year: '1234.50', year: 2026,
}
const CARD_STATS = {
  vin: 'V1', year: 2018, make: 'Honda', model: 'Accord',
  usage_unit: 'distance', secondary_usage_enabled: false,
  latest_odometer_km: CANONICAL_KM, latest_hours: null,
  average_l_per_100km: null, average_l_per_hr: null, recent_l_per_100km: null,
  total_service_records: 0, total_fuel_records: 0, total_odometer_records: 1,
}

/** Every mounted read site, by the call shape it exercises. */
const SITES: { name: string; mount: () => void }[] = [
  { name: 'FleetHealthStrip next-due mileage (formatPrimary)',
    mount: () => { render(<FleetHealthStrip fleet={FLEET} />) } },
  { name: 'VehicleHero odometer reading (formatPrimary)',
    mount: () => {
      render(<VehicleHero vehicle={VEHICLE} photoUrl={null} fromCache={false} detailStats={HERO_STATS} />)
    } },
  { name: 'VehicleStatisticsCard latest odometer (formatPrimary)',
    mount: () => { render(<VehicleStatisticsCard stats={CARD_STATS as never} />) } },
  { name: 'OdometerRecordList row and hero (format)',
    mount: () => { render(<OdometerRecordList vin="V1" onAddClick={vi.fn()} onEditClick={vi.fn()} />) } },
  { name: 'WarrantyList mileage limit (format)',
    mount: () => { render(<WarrantyList vin="V1" onAddClick={vi.fn()} onEditClick={vi.fn()} />) } },
  { name: 'ServiceVisitList odometer (format)',
    mount: () => { render(<ServiceVisitList vin="V1" onAddClick={vi.fn()} onEditClick={vi.fn()} />) } },
  { name: 'ReminderList due mileage (format)',
    mount: () => { render(<ReminderList vin="V1" />) } },
  { name: 'DEFRecordList odometer column (format)',
    mount: () => { render(<DEFRecordList vin="V1" />) } },
]

beforeEach(() => {
  unitPrefMock.units = METRIC_UNITS
})

describe.each(SITES)('$name', ({ mount }) => {
  it('reads MILES for a litres-and-miles client, where `system` says metric', () => {
    unitPrefMock.units = LITRES_MILES
    mount()
    expect(screen.getAllByText(AS_MILES).length).toBeGreaterThan(0)
    expect(screen.queryByText(AS_KM)).not.toBeInTheDocument()
  })

  it('reads KILOMETRES for a gallons-and-kilometres client, where `system` says imperial', () => {
    unitPrefMock.units = GALLONS_KM
    mount()
    expect(screen.getAllByText(AS_KM).length).toBeGreaterThan(0)
    expect(screen.queryByText(AS_MILES)).not.toBeInTheDocument()
  })
})

describe('the sites that render a unit label of their own', () => {
  it('OdometerRecordList column header interpolates the resolved distance label', () => {
    unitPrefMock.units = LITRES_MILES
    render(<OdometerRecordList vin="V1" onAddClick={vi.fn()} onEditClick={vi.fn()} />)
    expect(
      screen.getByRole('columnheader', { name: 'odometerRecordList.mileageColumn (mi)' })
    ).toBeInTheDocument()
  })

  it('the DEF estimate card names the resolved unit and converts the number beside it', () => {
    // `Est. {label} Left` over `toDisplayText`: 80467 km is 50,000 mi, and the
    // card used to answer "80,467" under an "Est. km Left" caption for this
    // account because both halves read the collapsed system.
    unitPrefMock.units = LITRES_MILES
    render(<DEFRecordList vin="V1" />)
    const card = screen.getByText(/Est\./).closest('div')?.parentElement as HTMLElement
    expect(within(card).getByText(/Est\. mi Left/)).toBeInTheDocument()
    expect(within(card).getByText('50,000')).toBeInTheDocument()
  })

  it('the DEF consumption card quotes the rate in BOTH of the reader units', () => {
    // The compound the units gate cannot see: `formatVolumePerDistance(units)`
    // was CALL-SITE IDENTICAL to the correct `formatVolume(units)` and derived
    // its DISTANCE half from `units.volume`. For this account it answered
    // '3.4' under an 'L/1,000 km' label while the odometer column beside it
    // read miles. 3.4 x 1.60934 = 5.471756, one decimal 5.5.
    unitPrefMock.units = LITRES_MILES
    render(<DEFRecordList vin="V1" />)
    expect(screen.getByText('5.5')).toBeInTheDocument()
    expect(screen.getByText('L/1,000 mi')).toBeInTheDocument()
    expect(screen.queryByText('L/1,000 km')).not.toBeInTheDocument()
  })

  it('and the mirror: a gallons-and-kilometres account gets gal per 1,000 km', () => {
    // 3.4 L / 3.78541 = 0.898 US gal per 1,000 km, one decimal 0.9. The retired
    // helper multiplied by 1.60934 anyway and answered 1.4 under 'gal/1,000 mi'.
    unitPrefMock.units = GALLONS_KM
    render(<DEFRecordList vin="V1" />)
    expect(screen.getByText('0.9')).toBeInTheDocument()
    expect(screen.getByText('gal/1,000 km')).toBeInTheDocument()
    expect(screen.queryByText('gal/1,000 mi')).not.toBeInTheDocument()
  })
})
