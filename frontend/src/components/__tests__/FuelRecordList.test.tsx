import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within, waitFor, fireEvent } from '@testing-library/react'
import type { FuelRecord } from '../../types/fuel'

// Query hooks + api mocked so this stays a unit test (no QueryClient/network).
const useFuelRecordsMock = vi.fn()
const useDeleteFuelRecordMock = vi.fn()
const useImportFuelCSVMock = vi.fn()
const apiGetMock = vi.fn()
const deleteMutate = vi.fn()

vi.mock('../../hooks/queries/useFuelRecords', () => ({
  useFuelRecords: () => useFuelRecordsMock(),
  useDeleteFuelRecord: () => useDeleteFuelRecordMock(),
  useImportFuelCSV: () => useImportFuelCSVMock(),
}))
vi.mock('../../services/api', () => ({ default: { get: (...a: unknown[]) => apiGetMock(...a) } }))
// Mutable so the unit-aware volume-header test (B7) can toggle metric/imperial;
// every other test leaves it at the metric default set in beforeEach.
const unitPrefMock = vi.hoisted(() => ({
  system: 'metric' as 'metric' | 'imperial',
  showBoth: false,
  // Set to pin an exact resolved set (a `gal_uk` user, say); left null the set
  // follows `system`, the way the real hook derives both on one rung.
  units: null as null | import('@/types/units').UnitSet,
}))
vi.mock('../../hooks/useUnitPreference', async () => {
  const { IMPERIAL_UNITS, METRIC_UNITS } = await import('@/__tests__/factories')
  return {
    useUnitPreference: () => ({
      system: unitPrefMock.system,
      showBoth: unitPrefMock.showBoth,
      units:
        unitPrefMock.units ??
        (unitPrefMock.system === 'imperial' ? IMPERIAL_UNITS : METRIC_UNITS),
    }),
  }
})
// LOCAL i18n mock (same pattern as the plan's DEF/Propane B5 fix — see
// task-3-review.md Important #1): the GLOBAL setup.ts mock is `t: (key) => key`,
// which discards interpolation args, so `t('fuelList.volumeUnit', { unit })` renders
// the identical string regardless of unit — a header test against it can't tell L
// from gal, or from a dropped {{unit}} entirely. This override retains `options.unit`
// for the volume-header assertions below and is otherwise behaviour-identical to the
// global mock (bare key, no unit) so the other 11 tests in this file stay green.
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    // `value` as well as `unit`: fix round 1 routed the volume-total and
    // avg-cost captions through `t()` with an interpolated NUMBER, and a mock
    // that dropped it would render the same key for 10.4 gal and 47.3 L.
    t: (key: string, options?: { unit?: string; value?: string }) =>
      options?.unit !== undefined || options?.value !== undefined
        ? `${key} (${options.unit ?? options.value})`
        : key,
    i18n: { language: 'en', changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children: React.ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: () => {} },
}))
// NOTE: the component imports formatCurrency from utils/formatUtils (NOT from this
// hook), so the REAL formatter runs: formatCurrency(43.75) → "$43.75" and
// formatCurrency(0) → "-" (NEVER "$0.00"). Assertions use the real output; the old
// plan's `getAllByText('$0.00')` was a dead assertion — that string is never rendered.
vi.mock('../../hooks/useCurrencyPreference', () => ({
  useCurrencyPreference: () => ({ currencyCode: 'USD', locale: 'en-US' }),
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import { IMPERIAL_UNITS, METRIC_UNITS, UK_IMPERIAL_UNITS } from '../../__tests__/factories'
import { binarySystemFor } from '../../types/units'
import { UnitConverter } from '../../utils/units'
import FuelRecordList from '../FuelRecordList'

const record: FuelRecord = {
  id: 1,
  vin: 'TEST12345678901234',
  date: '2026-03-01',
  odometer_km: '80467',
  liters: '47.318',
  propane_liters: null,
  price_per_unit: '0.925',
  price_basis: 'per_volume',
  cost: '43.75',
  l_per_100km: '7.200',        // DISTINCT from the tile average (8.5) → no ambiguous /8.5/ match
  is_full_tank: true,
  is_hauling: true,
  notes: 'topped off',
} as FuelRecord

const onAddClick = vi.fn()
const onEditClick = vi.fn()
const DEFAULT_PROPS = { vin: 'TEST12345678901234', onAddClick, onEditClick }

// The DataTable renders its caption as the table's accessible name, so this
// scopes every assertion to the row region — the whole point of B1/B2.
const table = () => screen.getByRole('table', { name: 'fuelList.tableCaption' })

beforeEach(() => {
  vi.clearAllMocks()
  unitPrefMock.system = 'metric'
  unitPrefMock.units = null
  UnitConverter.setGallonStandard('us')
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  useFuelRecordsMock.mockReturnValue({
    data: { records: [record], total: 1, average_l_per_100km: '8.5' },
    isLoading: false,
    error: null,
  })
  useDeleteFuelRecordMock.mockReturnValue({ mutate: deleteMutate, isPending: false, variables: undefined })
  useImportFuelCSVMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
  apiGetMock.mockResolvedValue({ data: { fuel_type: 'gasoline' } })
})

describe('FuelRecordList — row cells scoped to the named table', () => {
  it('renders the row economy badge and the row cost INSIDE the table (fails if the economy or cost column is dropped; scoping stops a summary tile from satisfying it)', async () => {
    render(<FuelRecordList {...DEFAULT_PROPS} />)
    await waitFor(() => expect(apiGetMock).toHaveBeenCalled())
    // real formatFuelEconomy(7.2,'metric') → "7.2 L/100km" — 7.2 appears only in the row badge
    expect(within(table()).getByText(/7\.2/)).toBeInTheDocument()
    // real formatCurrency(43.75) → "$43.75"; the Total-Spent tile also shows "$43.75"
    // but lives OUTSIDE the table, so scoping proves the row cost CELL renders.
    expect(within(table()).getByText(/43\.75/)).toBeInTheDocument()
  })

  it('uses the truthful generic price header, not a volume-only one (B8) (fails if the header reverts to a per-volume `fuelList.pricePerUnit`)', async () => {
    render(<FuelRecordList {...DEFAULT_PROPS} />)
    await waitFor(() => expect(apiGetMock).toHaveBeenCalled())
    expect(within(table()).getByRole('columnheader', { name: 'fuelList.unitPrice' })).toBeInTheDocument()
    expect(within(table()).queryByRole('columnheader', { name: 'fuelList.pricePerUnit' })).not.toBeInTheDocument()
  })

  it('renders a per-WEIGHT row price under that SAME generic header (B8) (fails if the per-weight value is dropped or the header is basis-specific)', async () => {
    const perWeight = { ...record, id: 2, price_basis: 'per_weight', price_per_unit: '1.850' } as FuelRecord
    useFuelRecordsMock.mockReturnValue({ data: { records: [perWeight], total: 1, average_l_per_100km: '8.5' }, isLoading: false, error: null })
    render(<FuelRecordList {...DEFAULT_PROPS} />)
    await waitFor(() => expect(apiGetMock).toHaveBeenCalled())
    // metric priceToDisplay(per_weight) passes the value through → formatCurrency(1.85) → "$1.85"
    expect(within(table()).getByText(/1\.85/)).toBeInTheDocument()
    expect(within(table()).getByRole('columnheader', { name: 'fuelList.unitPrice' })).toBeInTheDocument()
  })

  it('interpolates the SYSTEM volume unit into the header — L in metric, gal in imperial (fails if the impl omits {{unit}}, hardcodes one system, or reverts to a static key)', async () => {
    unitPrefMock.system = 'metric'
    const metric = render(<FuelRecordList {...DEFAULT_PROPS} />)
    await waitFor(() => expect(apiGetMock).toHaveBeenCalled())
    expect(within(table()).getByRole('columnheader', { name: 'fuelList.volumeUnit (L)' })).toBeInTheDocument()
    metric.unmount()

    unitPrefMock.system = 'imperial'
    render(<FuelRecordList {...DEFAULT_PROPS} />)
    await waitFor(() => expect(apiGetMock).toHaveBeenCalled())
    expect(within(table()).getByRole('columnheader', { name: 'fuelList.volumeUnit (gal)' })).toBeInTheDocument()
  })

  it('shows the Full-tank badge (true) and the towing badge (true) IN-table (fails if either status column is dropped)', async () => {
    render(<FuelRecordList {...DEFAULT_PROPS} />)
    await waitFor(() => expect(apiGetMock).toHaveBeenCalled())
    expect(within(table()).getByText('fuelList.full')).toBeInTheDocument()
    expect(within(table()).getByText('fuelList.towing')).toBeInTheDocument()
  })

  it('renders the FALSE status states — partial badge + no towing badge (fails if the false branch is missing or swapped)', async () => {
    const plain = { ...record, is_full_tank: false, is_hauling: false } as FuelRecord
    useFuelRecordsMock.mockReturnValue({ data: { records: [plain], total: 1, average_l_per_100km: '8.5' }, isLoading: false, error: null })
    render(<FuelRecordList {...DEFAULT_PROPS} />)
    await waitFor(() => expect(apiGetMock).toHaveBeenCalled())
    expect(within(table()).getByText('fuelList.partial')).toBeInTheDocument()
    expect(within(table()).queryByText('fuelList.full')).not.toBeInTheDocument()
    expect(within(table()).queryByText('fuelList.towing')).not.toBeInTheDocument()
  })
})

describe('FuelRecordList — row actions fire the real handlers', () => {
  it('clicking row Edit calls onEditClick with THE WHOLE record (fails if edit is unwired, passes the wrong row, or passes a truncated object)', async () => {
    render(<FuelRecordList {...DEFAULT_PROPS} />)
    await waitFor(() => expect(apiGetMock).toHaveBeenCalled())
    fireEvent.click(within(table()).getByRole('button', { name: 'common:edit' }))
    // Contract is onEditClick(record: FuelRecord) (FuelRecordList.tsx:17); the render passes the
    // row object straight through (onClick={() => onEditClick(r)}), and rows are a filtered (not
    // mapped) view of the fixture, so assert the FULL record. objectContaining({ id }) would have
    // survived a truncated { id: 1 } that opened an edit form missing every other field.
    expect(onEditClick).toHaveBeenCalledWith(record)
  })

  it('clicking row Delete (confirm accepted) calls the delete mutation with the record id (fails if delete is unwired or the confirm gate is dropped)', async () => {
    render(<FuelRecordList {...DEFAULT_PROPS} />)
    await waitFor(() => expect(apiGetMock).toHaveBeenCalled())
    fireEvent.click(within(table()).getByRole('button', { name: 'common:delete' }))
    expect(window.confirm).toHaveBeenCalled()
    expect(deleteMutate).toHaveBeenCalledWith(1, expect.anything())
  })

  it('exposes row edit + delete by accessible NAME (not title alone) (fails if IconButton loses aria-label)', async () => {
    render(<FuelRecordList {...DEFAULT_PROPS} />)
    await waitFor(() => expect(apiGetMock).toHaveBeenCalled())
    expect(within(table()).getByRole('button', { name: 'common:edit' })).toBeInTheDocument()
    expect(within(table()).getByRole('button', { name: 'common:delete' })).toBeInTheDocument()
  })
})

describe('FuelRecordList — conditional propane column', () => {
  it('renders the propane column header ONLY for a propane vehicle (fails if the column is always- or never-shown)', async () => {
    apiGetMock.mockResolvedValue({ data: { fuel_type: 'propane' } })
    const propaneRec = { ...record, propane_liters: '39.750' } as FuelRecord
    useFuelRecordsMock.mockReturnValue({ data: { records: [propaneRec], total: 1, average_l_per_100km: null }, isLoading: false, error: null })
    render(<FuelRecordList {...DEFAULT_PROPS} />)
    // header appears only after the async vehicle fetch resolves → findByRole waits.
    // Also carries `{ unit }` (same as the volume header, B7) — the local i18n mock
    // now retains it, so the accessible name is the interpolated form (metric default: L).
    expect(await screen.findByRole('columnheader', { name: 'fuelList.propaneUnit (L)' })).toBeInTheDocument()
  })

  it('omits the propane column for a non-propane vehicle', async () => {
    render(<FuelRecordList {...DEFAULT_PROPS} />)
    await waitFor(() => expect(apiGetMock).toHaveBeenCalled())
    // The real header renders interpolated (`fuelList.propaneUnit (L)` via the file-local
    // {{unit}}-retaining mock), so an exact `name: 'fuelList.propaneUnit'` never matches and
    // would pass even if a bug made the column always-on. Regex matches the interpolated form,
    // so this now FAILS if the propane column ever renders for a non-propane vehicle.
    expect(screen.queryByRole('columnheader', { name: /fuelList\.propaneUnit/ })).not.toBeInTheDocument()
  })
})

describe('FuelRecordList — hours usage tracking (Task 13)', () => {
  // Distinct decimals from the distance-side fixtures (7.2 / 8.5 / 43.75) so
  // regex text matches below can't accidentally hit the wrong number.
  const hoursRecord: FuelRecord = { ...record, id: 3, l_per_hr: '3.20', engine_hours: '812.4' } as FuelRecord
  const HOURS_DATA = {
    records: [hoursRecord],
    total: 1,
    average_l_per_100km: null,
    average_l_per_hr: '4.50',
    average_cost_per_hr: '2.75',
  }

  it('shows the Fuel Rate column and per-row fuel rate, and hides Mileage/Fuel Economy, for an hours-tracking vehicle', async () => {
    apiGetMock.mockResolvedValue({ data: { fuel_type: 'gasoline', usage_unit: 'hours', secondary_usage_enabled: false } })
    useFuelRecordsMock.mockReturnValue({ data: HOURS_DATA, isLoading: false, error: null })
    render(<FuelRecordList {...DEFAULT_PROPS} />)

    expect(await screen.findByRole('columnheader', { name: 'fuelList.fuelRate' })).toBeInTheDocument()
    // real formatFuelRate(3.2, 'metric') -> "3.20 L/hr"
    expect(within(table()).getByText(/3\.20/)).toBeInTheDocument()
    expect(within(table()).queryByRole('columnheader', { name: 'fuelList.mileage' })).not.toBeInTheDocument()
    expect(within(table()).queryByRole('columnheader', { name: 'fuelList.fuelEconomy' })).not.toBeInTheDocument()
  })

  it('shows the Avg fuel-rate and Cost/hr stat cards, and hides Avg Fuel Economy, for an hours-tracking vehicle', async () => {
    apiGetMock.mockResolvedValue({ data: { fuel_type: 'gasoline', usage_unit: 'hours', secondary_usage_enabled: false } })
    useFuelRecordsMock.mockReturnValue({ data: HOURS_DATA, isLoading: false, error: null })
    render(<FuelRecordList {...DEFAULT_PROPS} />)
    await waitFor(() => expect(apiGetMock).toHaveBeenCalled())

    // real formatFuelRate(4.5, 'metric') -> "4.50 L/hr"; formatCurrency(2.75) -> "$2.75"
    expect(await screen.findByText('4.50 L/hr')).toBeInTheDocument()
    expect(screen.getByText('$2.75')).toBeInTheDocument()
    expect(screen.queryByText('fuelList.avgFuelEconomy')).not.toBeInTheDocument()
  })

  it('keeps Mileage + Fuel Economy and omits Fuel Rate / hours stats for a pure-distance vehicle (table unchanged)', async () => {
    // apiGetMock default (beforeEach) returns fuel_type only — no usage_unit, defaults to distance.
    render(<FuelRecordList {...DEFAULT_PROPS} />)
    await waitFor(() => expect(apiGetMock).toHaveBeenCalled())

    expect(within(table()).getByRole('columnheader', { name: 'fuelList.mileage' })).toBeInTheDocument()
    expect(within(table()).getByRole('columnheader', { name: 'fuelList.fuelEconomy' })).toBeInTheDocument()
    expect(within(table()).queryByRole('columnheader', { name: 'fuelList.fuelRate' })).not.toBeInTheDocument()
    expect(screen.queryByText('fuelList.costPerHour')).not.toBeInTheDocument()
  })

  it('shows BOTH mileage/economy AND fuel-rate columns/stats for a dual-tracking vehicle', async () => {
    apiGetMock.mockResolvedValue({ data: { fuel_type: 'gasoline', usage_unit: 'distance', secondary_usage_enabled: true } })
    useFuelRecordsMock.mockReturnValue({
      data: { ...HOURS_DATA, average_l_per_100km: '8.5' },
      isLoading: false,
      error: null,
    })
    render(<FuelRecordList {...DEFAULT_PROPS} />)

    expect(await screen.findByRole('columnheader', { name: 'fuelList.mileage' })).toBeInTheDocument()
    expect(within(table()).getByRole('columnheader', { name: 'fuelList.fuelEconomy' })).toBeInTheDocument()
    expect(within(table()).getByRole('columnheader', { name: 'fuelList.fuelRate' })).toBeInTheDocument()
    expect(screen.getByText('fuelList.avgFuelEconomy')).toBeInTheDocument()
    expect(screen.getByText('$2.75')).toBeInTheDocument()
  })

  it('★ the economy badge follows units.consumption, not a system collapsed from volume', async () => {
    // `formatFuelEconomy(l, system)` read `system`, which spec D8 derives from
    // VOLUME. This account keeps litres and chose MPG, so the badge and the
    // tile both answered in L/100km however the preference was set.
    unitPrefMock.units = { ...METRIC_UNITS, consumption: 'mpg_us' }
    render(<FuelRecordList {...DEFAULT_PROPS} />)
    await waitFor(() => expect(apiGetMock).toHaveBeenCalled())

    // 235.214 / 7.2 = 32.7 in the row badge; / 8.5 = 27.7 on the tile.
    expect(within(table()).getByText('32.7 MPG')).toBeInTheDocument()
    expect(screen.getByText('27.7 MPG')).toBeInTheDocument()
    expect(within(table()).queryByText('7.20 L/100km')).not.toBeInTheDocument()
  })

  it('★ the fuel-rate column and card name the account\'s own gallon', async () => {
    // `formatFuelRate` divided by a MUTABLE static following the INSTANCE
    // gallon setting, so this UK account read 4.50 L/hr as "1.19 GPH" beside a
    // volume column that had already converted litres on the imperial gallon.
    unitPrefMock.system = 'imperial'
    unitPrefMock.units = { ...IMPERIAL_UNITS, volume: 'gal_uk', secondary_gallon: 'uk' }
    apiGetMock.mockResolvedValue({ data: { fuel_type: 'gasoline', usage_unit: 'hours', secondary_usage_enabled: false } })
    useFuelRecordsMock.mockReturnValue({ data: HOURS_DATA, isLoading: false, error: null })
    render(<FuelRecordList {...DEFAULT_PROPS} />)

    // 4.5 / 4.54609 = 0.99 on the card; 3.2 / 4.54609 = 0.70 in the row.
    expect(await screen.findByText('0.99 gal/hr')).toBeInTheDocument()
    expect(within(table()).getByText('0.70 gal/hr')).toBeInTheDocument()
    // The card's LABEL too, through the local i18n mock's `{{unit}}`: a label
    // that lost the `/hr` and read a bare `gal` would otherwise survive, since
    // the value beside it is unchanged.
    expect(screen.getByText('fuelList.avgFuelRate (gal/hr)')).toBeInTheDocument()
    // What the instance-wide US gallon would have answered for the same rows.
    expect(screen.queryByText('1.19 gal/hr')).not.toBeInTheDocument()
    expect(screen.queryByText('1.19 GPH')).not.toBeInTheDocument()
  })

  it('hides the cost-per-distance stat for a pure-hours vehicle even when odometer data is present, but keeps it for a distance vehicle', async () => {
    // Two fills with DISTINCT odometers so costPerKm is computable — this proves
    // the stat is gated on tracking MODE, not merely absent because it's null.
    // A pure-hours ATV can still carry odometer values under its fuel rows (older
    // distance data), which is exactly when the leak showed: a Cost/1k-Miles
    // figure on a vehicle you don't track by distance.
    const twoRecords = [
      { ...record, id: 10, odometer_km: '1000', l_per_hr: '3.20', engine_hours: '100.0' },
      { ...record, id: 11, odometer_km: '2000', l_per_hr: '3.30', engine_hours: '150.0' },
    ] as FuelRecord[]

    // ★ THE LABEL IS A TRANSLATED KEY NOW, and the string this case used to look
    // for is the evidence of why. It asserted the literal 'Cost/100 km', which
    // this file's `t` mock returns keys from: the label was never translated at
    // all, it was two hardcoded English strings inside
    // `UnitFormatter.getCostPerDistanceLabel`, shown to every reader of every
    // language. Task 7 routed it through `t('fuelList.costPerDistance', {unit})`
    // in all seven bundles, so the mock now renders `key (unit)` and the unit
    // half comes from the resolved DISTANCE token instead of a system collapsed
    // from volume.
    // Pure-hours: the stat is hidden regardless of what it would have said.
    apiGetMock.mockResolvedValue({ data: { fuel_type: 'gasoline', usage_unit: 'hours', secondary_usage_enabled: false } })
    useFuelRecordsMock.mockReturnValue({
      data: { records: twoRecords, total: 2, average_l_per_100km: null, average_l_per_hr: '4.50', average_cost_per_hr: '2.75' },
      isLoading: false,
      error: null,
    })
    const hours = render(<FuelRecordList {...DEFAULT_PROPS} />)
    await screen.findByText('4.50 L/hr') // hours state applied before asserting absence
    expect(screen.queryByText('fuelList.costPerDistance (100 km)')).not.toBeInTheDocument()
    hours.unmount()

    // Pure-distance, same records: the cost-per-distance stat returns.
    apiGetMock.mockResolvedValue({ data: { fuel_type: 'gasoline', usage_unit: 'distance', secondary_usage_enabled: false } })
    useFuelRecordsMock.mockReturnValue({
      data: { records: twoRecords, total: 2, average_l_per_100km: '8.5' },
      isLoading: false,
      error: null,
    })
    render(<FuelRecordList {...DEFAULT_PROPS} />)
    expect(await screen.findByText('fuelList.costPerDistance (100 km)')).toBeInTheDocument()
  })
})

describe('FuelRecordList — the cost-per-distance card, label and value together', () => {
  // ★ THE HALF-MIGRATED PAIR THIS CLOSES. Task 6 moved the odometer column onto
  // `units.distance` and left this card on the binary system, which spec D8
  // collapses from VOLUME. A `{volume:'L', distance:'mi'}` account therefore
  // read a miles odometer beside a "Cost/100 km" caption over a per-100-km
  // figure: before task 6 both halves were wrong together, which is less
  // visible and no more correct. Both halves are asserted in every case here,
  // because a label that moves without its value is the same defect inverted.
  const twoFills = [
    { ...record, id: 30, odometer_km: '1000', cost: '10.00' },
    { ...record, id: 31, odometer_km: '2000', cost: '10.00' },
  ] as FuelRecord[]

  beforeEach(() => {
    apiGetMock.mockResolvedValue({
      data: { fuel_type: 'gasoline', usage_unit: 'distance', secondary_usage_enabled: false },
    })
    useFuelRecordsMock.mockReturnValue({
      data: { records: twoFills, total: 2, average_l_per_100km: '8.5' },
      isLoading: false,
      error: null,
    })
  })

  it('★ a LITRES-and-MILES account reads its cost per 1,000 MILES', async () => {
    // $20.00 over 1000 km is $0.02/km; x 1.60934 x 1000 = $32.19 per 1,000 mi.
    // The retired pair read 'metric' off the litres and answered $2.00 under
    // "Cost/100 km", beside an odometer column already reading miles.
    unitPrefMock.units = { ...METRIC_UNITS, distance: 'mi', speed: 'mph' }

    render(<FuelRecordList {...DEFAULT_PROPS} />)
    expect(await screen.findByText('fuelList.costPerDistance (1,000 mi)')).toBeInTheDocument()
    expect(screen.getByText('$32.19')).toBeInTheDocument()
    // The two answers the collapsed decision would have given, named so this
    // cannot pass on a build that merely relabelled the card.
    expect(screen.queryByText('fuelList.costPerDistance (100 km)')).not.toBeInTheDocument()
    expect(screen.queryByText('$2.00')).not.toBeInTheDocument()
    // And the collapse really does disagree, so the case is not a coincidence.
    expect(binarySystemFor(unitPrefMock.units.volume)).toBe('metric')
  })

  it('★ the MIRROR, gallons with kilometres, reads its cost per 100 KILOMETRES', async () => {
    // Without this, everything above is satisfied by code that merely inverted
    // the branch. $0.02/km x 1 x 100 = $2.00 per 100 km.
    unitPrefMock.units = { ...IMPERIAL_UNITS, distance: 'km', speed: 'kmh' }

    render(<FuelRecordList {...DEFAULT_PROPS} />)
    expect(await screen.findByText('fuelList.costPerDistance (100 km)')).toBeInTheDocument()
    expect(screen.getByText('$2.00')).toBeInTheDocument()
    expect(screen.queryByText('$32.19')).not.toBeInTheDocument()
    expect(binarySystemFor(unitPrefMock.units.volume)).toBe('imperial')
  })

  it('leaves both uniform accounts exactly where they were', async () => {
    // The controls. Neither denominator changed in this task, and a fix that
    // moved one would be a different bug rather than a fix.
    unitPrefMock.units = METRIC_UNITS
    const metric = render(<FuelRecordList {...DEFAULT_PROPS} />)
    expect(await screen.findByText('fuelList.costPerDistance (100 km)')).toBeInTheDocument()
    expect(screen.getByText('$2.00')).toBeInTheDocument()
    metric.unmount()

    unitPrefMock.units = IMPERIAL_UNITS
    render(<FuelRecordList {...DEFAULT_PROPS} />)
    expect(await screen.findByText('fuelList.costPerDistance (1,000 mi)')).toBeInTheDocument()
    expect(screen.getByText('$32.19')).toBeInTheDocument()
  })
})

describe('FuelRecordList — empty state CTA is wired', () => {
  it('shows the "no records" empty state and its add-first CTA fires onAddClick (fails if the CTA is unwired or the title text changes)', () => {
    useFuelRecordsMock.mockReturnValue({ data: { records: [], total: 0, average_l_per_100km: null }, isLoading: false, error: null })
    render(<FuelRecordList {...DEFAULT_PROPS} />)
    expect(screen.getByText('fuelList.noRecords')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'fuelList.addFirstFillUp' }))
    expect(onAddClick).toHaveBeenCalled()
  })
})

describe('FuelRecordList — one gallon per page, taken from the user', () => {
  // ★ The plan's stated failure mode: fixing `decimalSafe` alone would make a
  // UK user's ROW read $4.55/gal while the summary card on the SAME PAGE still
  // read $3.79/gal, because `formatCostPerVolume` held its own hardcoded
  // 3.78541. The row's volume, the row's price and both volume cards have to
  // come from one resolved set, and the instance's own flavour is not it.
  it('renders the header, the volume cell, the price cell and both volume cards on the imperial gallon', async () => {
    UnitConverter.setGallonStandard('us')
    unitPrefMock.system = 'imperial'
    unitPrefMock.units = UK_IMPERIAL_UNITS

    render(<FuelRecordList {...DEFAULT_PROPS} />)
    await waitFor(() => expect(apiGetMock).toHaveBeenCalled())

    const t = table()
    // 47.318 L is 10.41 imperial gallons; 12.50 US ones.
    expect(within(t).getByRole('columnheader', { name: 'fuelList.volumeUnit (gal)' })).toBeInTheDocument()
    expect(within(t).getByText('10.41 gal')).toBeInTheDocument()
    // $0.925/L is $4.21/imperial gal, $3.50/US gal.
    expect(within(t).getByText('$4.21')).toBeInTheDocument()
    // Summary cards, OUTSIDE the table, on the same gallon.
    expect(screen.getByText('fuelList.volumeTotal (10.4 gal)')).toBeInTheDocument()
    expect(screen.getByText('fuelList.avgCostPerVolume (gal)')).toBeInTheDocument()
    expect(screen.getByText('$4.20')).toBeInTheDocument()
    expect(UnitConverter.getGallonStandard()).toBe('us')
  })

  it('renders litres everywhere for a metric set, even on a UK-default instance', async () => {
    UnitConverter.setGallonStandard('uk')
    unitPrefMock.system = 'metric'
    unitPrefMock.units = null

    render(<FuelRecordList {...DEFAULT_PROPS} />)
    await waitFor(() => expect(apiGetMock).toHaveBeenCalled())

    expect(within(table()).getByRole('columnheader', { name: 'fuelList.volumeUnit (L)' })).toBeInTheDocument()
    expect(within(table()).getByText('47.32 L')).toBeInTheDocument()
    expect(screen.getByText('fuelList.volumeTotal (47.3 L)')).toBeInTheDocument()
    expect(screen.getByText('fuelList.avgCostPerVolume (L)')).toBeInTheDocument()
  })
})
