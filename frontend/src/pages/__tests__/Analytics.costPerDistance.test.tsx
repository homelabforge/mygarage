/**
 * The analytics page's cost-per-distance card and its CSV row, both halves.
 *
 * ★ WHY THIS FILE EXISTS, and it is a coverage hole rather than a new subject.
 * Plan 3b task 7 migrated five call sites of `UnitFormatter.formatCostPerDistance`
 * / `getCostPerDistanceLabel` onto the resolved `units.distance` token. Its
 * mutation table found the two in `Analytics.tsx` completely unpinned: fixing
 * BOTH of them to a kilometre set killed nothing at all, twice, while the two
 * sites in `FuelRecordList.tsx` were caught immediately. Correct code, no guard.
 *
 * ★ THE SET IS `{volume:'L', distance:'mi'}`, which no binary system can
 * express. `binarySystemFor('L')` is `'metric'`, so anything deriving the
 * distance from the volume token, or from the collapsed system, quotes this
 * account per 100 km while task 6 has already given it a miles odometer. The
 * mirror block uses gallons with kilometres, so no assertion can be satisfied
 * by a branch that always answers one of them.
 *
 * ★ THE LABEL AND THE VALUE ARE ASSERTED TOGETHER, every time. A label that
 * moves without its number is this phase's recurring defect inverted, and it is
 * exactly the state task 6 left this card in.
 *
 * ★ THE CSV ROW IS READ OUT OF THE BLOB, not inferred. That row carried the
 * retired helper's hardcoded English into a downloaded file, and it is the one
 * of the three sites a rendering test cannot see.
 *
 * ★ IT ALSO CARRIES THE DEF-ANALYSIS AVG-COST CAPTION, which is a different
 * quantity and lives here for a practical reason worth stating rather than
 * hiding. Fix round 1 routed `getCostPerVolumeLabel` through `t()` at its four
 * render sites; three are list components with their own tests, and the fourth
 * is on this page, where the only mock that RETAINS an interpolated unit is the
 * one below. A caption asserted through the global `t: (key) => key` cannot
 * tell `gal` from `L`, which is the precise reason the caption this file was
 * written for went unnoticed for so long.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, cleanup, fireEvent } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import type { ReactNode } from 'react'
import type { VehicleAnalytics } from '../../types/analytics'

vi.mock('recharts', () => {
  const Pass = ({ children }: { children?: ReactNode }) => <>{children}</>
  return {
    ResponsiveContainer: Pass,
    LineChart: Pass,
    BarChart: Pass,
    PieChart: Pass,
    RadarChart: Pass,
    Line: () => null,
    Bar: () => null,
    Pie: () => null,
    Cell: () => null,
    Radar: () => null,
    PolarGrid: () => null,
    PolarAngleAxis: () => null,
    PolarRadiusAxis: () => null,
    XAxis: () => null,
    YAxis: () => null,
    CartesianGrid: () => null,
    Tooltip: () => null,
    Legend: () => null,
  }
})

vi.mock('../../services/api', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
    defaults: { headers: { common: {} } },
  },
}))

// LOCAL i18n mock that RETAINS interpolated values, for the reason
// `Analytics.consumptionUnits.test.tsx` states at length: the global
// `t: (key) => key` renders `vehicle.costPerDistance` whatever unit is
// interpolated into it, so a DOM assertion against it cannot tell `100 km` from
// `1,000 mi` or from a dropped interpolation entirely. That is not a
// hypothetical: the label this replaces bypassed `t()` altogether, and the test
// that watched this card asserted the raw English through a `(key) => key`
// mock, which is why nobody noticed.
//
// `t` and `i18n` are HOISTED to module scope, not rebuilt per call: this page
// lists `t` in effect dependency arrays, so a fresh `t` per render re-fires the
// analytics fetch forever.
vi.mock('react-i18next', () => {
  const t = (key: string, options?: Record<string, unknown>): string => {
    if (options?.defaultValue !== undefined) return String(options.defaultValue)
    const values = Object.entries(options ?? {}).map(([, v]) => String(v))
    return values.length > 0 ? `${key} (${values.join(' | ')})` : key
  }
  const i18n = { language: 'en', changeLanguage: () => Promise.resolve() }
  return {
    useTranslation: () => ({ t, i18n }),
    Trans: ({ children }: { children: ReactNode }) => children,
    initReactI18next: { type: '3rdParty', init: () => {} },
  }
})

import { IMPERIAL_UNITS, METRIC_UNITS } from '@/__tests__/factories'
import { binarySystemFor, type UnitSet } from '@/types/units'
import type { DEFAnalysis } from '../../types/analytics'

const unitPreferenceMock = vi.fn()
vi.mock('../../hooks/useUnitPreference', () => ({
  useUnitPreference: () => unitPreferenceMock(),
}))
vi.mock('../../hooks/useCurrencyPreference', () => ({
  useCurrencyPreference: () => ({ currencyCode: 'USD', locale: 'en-US' }),
}))
vi.mock('../../hooks/useCurrencySymbol', () => ({ useCurrencySymbol: () => '$' }))
vi.mock('../../hooks/useDateLocale', () => ({ useDateLocale: () => 'en-US' }))

import api from '../../services/api'
import Analytics from '../Analytics'

const mockedApiGet = vi.mocked(api).get

/** Litres for volume, miles for distance. `binarySystemFor('L')` is 'metric'. */
const LITRES_MILES: UnitSet = { ...METRIC_UNITS, distance: 'mi', speed: 'mph' }
/** The mirror: gallons for volume, kilometres for distance. */
const GALLONS_KM: UnitSet = { ...IMPERIAL_UNITS, distance: 'km', speed: 'kmh' }

/**
 * $0.02 per canonical kilometre, chosen so the two answers cannot be confused.
 *
 *   metric   0.02 x 1 x 100    = $2.00 per 100 km
 *   imperial 0.02 x 1.60934 x 1000 = $32.19 per 1,000 mi
 */
const COST_PER_KM = '0.02'

function baseAnalytics(overrides: Partial<VehicleAnalytics> = {}): VehicleAnalytics {
  return {
    vehicle_name: 'Test Car',
    vehicle_type: 'Car',
    vin: 'V1',
    days_owned: 100,
    total_km_driven: null,
    average_km_per_month: null,
    cost_analysis: {
      total_cost: '100.00',
      average_monthly_cost: '10.00',
      months_tracked: 10,
      service_count: 0,
      fuel_count: 2,
      def_count: 0,
      cost_per_km: COST_PER_KM,
      rolling_avg_3m: null,
      rolling_avg_6m: null,
      rolling_avg_12m: null,
      trend_direction: 'stable',
      total_service_cost: '0.00',
      total_fuel_cost: '100.00',
      total_def_cost: '0.00',
      monthly_breakdown: [],
      service_type_breakdown: [],
      anomalies: [],
    },
    cost_projection: {
      monthly_average: '10.00',
      six_month_projection: '60.00',
      twelve_month_projection: '120.00',
      assumptions: 'Projection assumes spending remains at recent averages.',
    },
    fuel_economy: {
      average_l_per_100km: null,
      best_l_per_100km: null,
      worst_l_per_100km: null,
      recent_l_per_100km: null,
      trend: 'stable',
      data_points: [],
    },
    hours_economy: {
      average_l_per_hr: null,
      average_cost_per_hr: null,
      best_l_per_hr: null,
      worst_l_per_hr: null,
      recent_l_per_hr: null,
      recent_cost_per_hr: null,
      trend: 'stable',
      data_points: [],
    },
    hours_accumulated: [],
    fuel_alerts: [],
    service_history: [],
    predictions: [],
    propane_analysis: null,
    spot_rental_analysis: null,
    def_analysis: null,
    ...overrides,
  } satisfies VehicleAnalytics
}

function mockAnalyticsResponse(analytics: VehicleAnalytics): void {
  mockedApiGet.mockImplementation((url: string) => {
    if (url.endsWith('/vendors')) return Promise.reject(new Error('no vendors'))
    if (url.endsWith('/seasonal')) return Promise.reject(new Error('no seasonal'))
    return Promise.resolve({ data: analytics })
  })
}

function renderAnalytics(): ReturnType<typeof render> {
  return render(
    <MemoryRouter initialEntries={['/vehicles/V1/analytics']}>
      <Routes>
        <Route path="/vehicles/:vin/analytics" element={<Analytics />} />
      </Routes>
    </MemoryRouter>
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  unitPreferenceMock.mockReturnValue({ system: 'metric', showBoth: false, units: METRIC_UNITS })
  mockAnalyticsResponse(baseAnalytics())
})

afterEach(() => {
  cleanup()
})

describe('Analytics — the cost-per-distance card follows units.distance', () => {
  it('★ a LITRES-and-MILES account reads its cost per 1,000 MILES', async () => {
    // The retired pair read 'metric' off the litres and answered '$2.00' under
    // 'Cost/100 km', beside an odometer task 6 had already migrated to miles.
    unitPreferenceMock.mockReturnValue({
      system: binarySystemFor(LITRES_MILES.volume),
      showBoth: false,
      units: LITRES_MILES,
    })
    renderAnalytics()

    expect(
      await screen.findByText('vehicle.costPerDistance (1,000 mi)')
    ).toBeInTheDocument()
    expect(screen.getByText('$32.19')).toBeInTheDocument()
    // The two answers the collapsed decision gave, named so this cannot pass on
    // a build that merely relabelled the card.
    expect(screen.queryByText('vehicle.costPerDistance (100 km)')).not.toBeInTheDocument()
    expect(screen.queryByText('$2.00')).not.toBeInTheDocument()
    // And the collapse really does disagree, so the case is not a coincidence.
    expect(binarySystemFor(LITRES_MILES.volume)).toBe('metric')
  })

  it('★ the MIRROR, gallons with kilometres, reads its cost per 100 KILOMETRES', async () => {
    // Without this, everything above is satisfied by code that merely inverted
    // the branch.
    unitPreferenceMock.mockReturnValue({
      system: binarySystemFor(GALLONS_KM.volume),
      showBoth: false,
      units: GALLONS_KM,
    })
    renderAnalytics()

    expect(await screen.findByText('vehicle.costPerDistance (100 km)')).toBeInTheDocument()
    expect(screen.getByText('$2.00')).toBeInTheDocument()
    expect(screen.queryByText('$32.19')).not.toBeInTheDocument()
    expect(binarySystemFor(GALLONS_KM.volume)).toBe('imperial')
  })

  it('leaves both uniform accounts exactly where they were', async () => {
    // The controls. Neither denominator changed in this task, and a fix that
    // moved one would be a different bug rather than a fix.
    unitPreferenceMock.mockReturnValue({ system: 'metric', showBoth: false, units: METRIC_UNITS })
    const metric = renderAnalytics()
    expect(await screen.findByText('vehicle.costPerDistance (100 km)')).toBeInTheDocument()
    expect(screen.getByText('$2.00')).toBeInTheDocument()
    metric.unmount()

    unitPreferenceMock.mockReturnValue({
      system: 'imperial',
      showBoth: false,
      units: IMPERIAL_UNITS,
    })
    renderAnalytics()
    expect(await screen.findByText('vehicle.costPerDistance (1,000 mi)')).toBeInTheDocument()
    expect(screen.getByText('$32.19')).toBeInTheDocument()
  })
})

describe('Analytics — the DEF-analysis avg-cost caption names the reader\'s volume unit', () => {
  // ★ The fourth `getCostPerVolumeLabel` site, and the only one not in a list
  // component. It returned the English words "Avg Cost/" glued to the unit
  // symbol, with no `t()`, so a German reader read `Avg Cost/gal` on a page
  // whose neighbouring caption (`vehicle.totalVolume`) had been interpolated
  // since task 6. Nothing rendered this card in any test: `def_analysis` is
  // null in both existing Analytics fixtures.
  // Declared as `DEFAnalysis` so every field is checked against the real
  // interface, then asserted into the unstructured dict the generated schema
  // types `def_analysis` as. That is the same assertion `Analytics.tsx:456`
  // makes in the other direction (`as DEFAnalysis | null | undefined`); the
  // backend really does return a dict there.
  const defAnalysis: DEFAnalysis = {
    total_spent: '120.00',
    total_liters: '47.317625',
    avg_cost_per_liter: '1.00',
    liters_per_1000_km: null,
    record_count: 3,
  }
  const asDict = { ...defAnalysis } as Record<string, unknown>

  it('★ reads the resolved volume unit, in both vocabularies', async () => {
    unitPreferenceMock.mockReturnValue({
      system: 'imperial',
      showBoth: false,
      units: IMPERIAL_UNITS,
    })
    mockAnalyticsResponse(baseAnalytics({ def_analysis: asDict }))
    const imperial = renderAnalytics()
    expect(await screen.findByText('vehicle.avgCostPerVolume (gal)')).toBeInTheDocument()
    // $1.00/L x 3.78541 = $3.79/gal, so the caption and the figure below it
    // name the same unit.
    expect(screen.getByText('$3.79')).toBeInTheDocument()
    imperial.unmount()

    unitPreferenceMock.mockReturnValue({ system: 'metric', showBoth: false, units: METRIC_UNITS })
    mockAnalyticsResponse(baseAnalytics({ def_analysis: asDict }))
    renderAnalytics()
    expect(await screen.findByText('vehicle.avgCostPerVolume (L)')).toBeInTheDocument()
    expect(screen.getByText('$1.00')).toBeInTheDocument()
  })
})

describe('Analytics — the CSV export carries the same denominator the card does', () => {
  /**
   * Drive the export menu and read the generated CSV out of the Blob.
   *
   * The page builds a Blob and clicks an anchor at it; jsdom implements neither
   * `URL.createObjectURL` nor a real download, so the object URL call is where
   * the content is intercepted. `link.click()` is stubbed too, since jsdom logs
   * "Not implemented: navigation" for it.
   */
  async function exportedCsv(): Promise<string> {
    const blobs: Blob[] = []
    const createObjectURL = vi
      .spyOn(URL, 'createObjectURL')
      .mockImplementation((blob: Blob | MediaSource) => {
        blobs.push(blob as Blob)
        return 'blob:mock'
      })
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    try {
      fireEvent.click(screen.getByRole('button', { name: 'exportMenu.export' }))
      fireEvent.click(await screen.findByRole('menuitem', { name: 'CSV' }))
      await waitFor(() => expect(blobs).toHaveLength(1))
      return await blobs[0].text()
    } finally {
      createObjectURL.mockRestore()
      click.mockRestore()
    }
  }

  it('★ a LITRES-and-MILES account exports the label AND the figure per 1,000 mi', async () => {
    // The site a rendering test cannot see. It carried the retired helper's
    // hardcoded English into a downloaded file, and it is the third of the
    // three sites that had to move together.
    unitPreferenceMock.mockReturnValue({
      system: binarySystemFor(LITRES_MILES.volume),
      showBoth: false,
      units: LITRES_MILES,
    })
    renderAnalytics()
    await screen.findByText('vehicle.costPerDistance (1,000 mi)')

    const csv = await exportedCsv()
    expect(csv).toContain('"vehicle.costPerDistance (1,000 mi)","$32.19"')
    expect(csv).not.toContain('vehicle.costPerDistance (100 km)')
    expect(csv).not.toContain('$2.00')
  })

  it('the MIRROR exports per 100 km, so the row is not a fixed string', async () => {
    unitPreferenceMock.mockReturnValue({
      system: binarySystemFor(GALLONS_KM.volume),
      showBoth: false,
      units: GALLONS_KM,
    })
    renderAnalytics()
    await screen.findByText('vehicle.costPerDistance (100 km)')

    const csv = await exportedCsv()
    expect(csv).toContain('"vehicle.costPerDistance (100 km)","$2.00"')
    expect(csv).not.toContain('$32.19')
  })
})
