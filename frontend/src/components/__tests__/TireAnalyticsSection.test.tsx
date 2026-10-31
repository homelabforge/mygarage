/**
 * The tire analytics section, and mostly its empty states.
 *
 * On the instance that asked for this feature, most of the page IS the empty
 * states: two tires, two readings, zero readings carrying an odometer. So
 * getting them wrong is the main risk in a read-only feature, and every row of
 * spec B's state table is a case here.
 *
 * **Every assertion below seeds the data that makes it meaningful.** A test
 * that passes because the section rendered nothing against an empty response
 * is not a test of an empty state, it is a test of an empty response.
 *
 * Imperial throughout, so the figures asserted are the TRANSFORMED ones. A
 * dimensionless assertion would pass whether or not the conversion ran, which
 * is how a units regression hides.
 */

import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import type React from 'react'
import { render, screen, waitFor } from '@testing-library/react'

const apiGet = vi.fn()
vi.mock('@/services/api', () => ({ default: { get: (...args: unknown[]) => apiGet(...args) } }))

/* Recharts renders nothing under jsdom: `ResponsiveContainer` measures its
 * parent, which has zero width, so the real chart produces an empty legend and
 * no series. Mocked down to what's worth asserting: WHICH tires get a series,
 * what each one is keyed and named by, and the rows the chart was handed. */
const chart = vi.hoisted(() => ({
  data: [] as Record<string, unknown>[],
  lines: [] as { dataKey: string; name: string }[],
}))
vi.mock('recharts', () => {
  const passthrough = ({ children }: { children?: React.ReactNode }) => <div>{children}</div>
  return {
    ResponsiveContainer: passthrough,
    LineChart: ({ data, children }: { data: Record<string, unknown>[]; children?: React.ReactNode }) => {
      chart.data = data
      chart.lines = []
      return <div>{children}</div>
    },
    CartesianGrid: () => null,
    XAxis: () => null,
    YAxis: () => null,
    Tooltip: () => null,
    Legend: () => null,
    // Recharts falls back to the dataKey for the legend when there's no name.
    Line: ({ dataKey, name }: { dataKey: string; name?: string }) => {
      chart.lines.push({ dataKey, name: name ?? dataKey })
      return <div data-testid="series">{name ?? dataKey}</div>
    },
  }
})

/* The global mock returns the bare key, which would hide the DOT code and the
 * number. So the legend keys render their real English template here, and
 * everything else stays a bare key like every other test expects. */
vi.mock('react-i18next', async () => {
  const en = (await import('../../locales/en/analytics.json')).default
  const tires = en.vehicle.tires as Record<string, string>
  const t = (key: string, opts?: Record<string, unknown>): string => {
    const leaf = key.replace('vehicle.tires.', '')
    if (!leaf.startsWith('trendSeries') || !(leaf in tires)) return key
    return tires[leaf].replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(opts?.[name]))
  }
  const i18n = { language: 'en', changeLanguage: () => Promise.resolve() }
  return { useTranslation: () => ({ t, i18n }) }
})

vi.mock('../../hooks/useUnitPreference', () => ({
  useUnitPreference: () => ({
    system: 'imperial',
    showBoth: false,
    gallonStandard: 'us',
    units: {
      consumption: 'mpg_us',
      distance: 'mi',
      length: 'ft',
      mass: 'lb',
      pressure: 'psi',
      secondary_gallon: 'us',
      speed: 'mph',
      temperature: 'f',
      torque: 'lbft',
      tread: 'in32',
      volume: 'gal_us',
    },
  }),
}))

import TireAnalyticsSection from '../TireAnalyticsSection'

const VIN = '1HGCM82633A004352'

const EMPTY_READINESS = {
  total: 0,
  can_trend: 0,
  can_project: 0,
  can_report_usage: 0,
  under_minimum: 0,
  needs_second_reading: 0,
  needs_reading_usage: 0,
  needs_minimum_tread: 0,
  needs_mount_odometer: 0,
}

const reading = (day: number, tread: string | null, odometer: string | null = '10000') => ({
  id: day,
  tire_id: 1,
  vin: VIN,
  position: 'FL',
  recorded_at: `2026-0${day}-01`,
  odometer_km: odometer,
  tread_depth_mm: tread,
  pressure_kpa: null,
  notes: null,
  created_at: '2026-01-01T00:00:00',
})

const tire = (over: Record<string, unknown> = {}) => ({
  id: 1,
  vin: VIN,
  position: 'FL',
  brand: 'Michelin',
  model_name: null,
  size: null,
  dot_code: null,
  set_id: null,
  retired_on: null,
  installed_date: null,
  tread_depth_mm: '8.00',
  pressure_kpa: null,
  min_tread_mm: '2.00',
  notes: null,
  below_threshold: false,
  projected_km_remaining: null,
  projected_wear_date: null,
  wear_status: 'insufficient_readings',
  distance_km: null,
  known_distance_km: null,
  known_distance_since: null,
  distance_status: 'no_periods',
  blocking_period_ids: [],
  mount_periods: [],
  readings: [],
  created_at: '2026-01-01T00:00:00',
  ...over,
})

const respond = (over: Record<string, unknown> = {}) =>
  apiGet.mockResolvedValue({
    data: {
      readiness: { ...EMPTY_READINESS, ...(over.readiness as object) },
      tires: (over.tires as unknown[]) ?? [],
      has_odometer_record: over.has_odometer_record ?? true,
    },
  })

/** Render and wait for the one fetch to land. */
const show = async () => {
  render(<TireAnalyticsSection vin={VIN} />)
  await waitFor(() => expect(apiGet).toHaveBeenCalled())
}

describe('TireAnalyticsSection', () => {
  afterEach(() => vi.restoreAllMocks())
  beforeEach(() => respond())

  it('renders nothing for a vehicle with no tires', async () => {
    // B9: gated on data presence, so a boat gets no empty blocks. Not on
    // vehicle type, which would exclude the trailers that do have tires.
    const { container } = render(<TireAnalyticsSection vin={VIN} />)
    await waitFor(() => expect(apiGet).toHaveBeenCalled())
    expect(container).toBeEmptyDOMElement()
  })

  it('renders for a vehicle that has tires', async () => {
    // The pair to the test above. Without it "renders nothing" is satisfied by
    // a component that renders nothing ever.
    respond({ tires: [tire()], readiness: { total: 1 } })
    await show()
    expect(screen.getByText('vehicle.tires.title')).toBeInTheDocument()
  })
})

describe('TireAnalyticsSection distance states', () => {
  afterEach(() => vi.restoreAllMocks())
  beforeEach(() => respond())

  it('never renders a spare as 0 km', async () => {
    // The case spec B's own v1 got wrong: the all-SPARE path returned a
    // running total of zero, so the one state that must never show a figure
    // was the one that did.
    respond({ tires: [tire({ distance_status: 'spare_only', distance_km: null })] })
    await show()

    expect(screen.queryByText(/0 mi/)).toBeNull()
    expect(screen.getAllByText('vehicle.tires.inStorage').length).toBeGreaterThan(0)
  })

  it('renders the prompt, not a number, for a migrated tire', async () => {
    // `nothing_bounded` is the state of EVERY tire the moment migration 097
    // runs, so this is the common case rather than an edge one.
    respond({ tires: [tire({ distance_status: 'nothing_bounded', blocking_period_ids: [4] })] })
    await show()

    expect(screen.getAllByText(/vehicle\.tires\.actionMountOdometer/).length).toBeGreaterThan(0)
    expect(screen.queryByText(/0 mi/)).toBeNull()
  })

  it('renders the measurable part of a partial history, with its date', async () => {
    respond({
      tires: [
        tire({
          distance_status: 'incomplete',
          known_distance_km: '19000',
          known_distance_since: '2026-01-05',
          distance_km: null,
        }),
      ],
    })
    await show()

    // 19,000 km = 11,806 mi at zero decimals. The transformed figure, so a
    // conversion that stopped running would fail this rather than pass it.
    expect(screen.getByText(/11,806 mi/)).toBeInTheDocument()
  })

  it('renders a complete distance in the reader unit', async () => {
    respond({ tires: [tire({ distance_status: 'complete', distance_km: '19000' })] })
    await show()
    expect(screen.getByText('11,806 mi')).toBeInTheDocument()
  })
})

describe('TireAnalyticsSection wear states', () => {
  afterEach(() => vi.restoreAllMocks())
  beforeEach(() => respond())

  it('suppresses the legacy projection rather than labelling it', async () => {
    // `unverified_mount_history` is the raw-delta path that reports 648,000 km
    // of life to a two-set owner. An "estimate" badge does not communicate
    // that a figure is structurally invalid rather than imprecise, so the
    // number is withheld and the prompt takes its place.
    respond({
      tires: [
        tire({ wear_status: 'unverified_mount_history', projected_km_remaining: '648000' }),
      ],
    })
    await show()

    // Asserted POSITIVELY, on the cell. The first version of this checked that
    // "648" was absent, which 648,000 km never renders as in miles (402,650),
    // so it passed whatever the code did.
    const row = screen.getByText(/Michelin/).closest('tr')
    expect(row).not.toBeNull()
    expect(row?.textContent).toContain('vehicle.tires.actionMountOdometer')
    expect(row?.textContent).not.toMatch(/~/)
  })

  it('renders a real projection in the reader unit', async () => {
    respond({
      tires: [
        tire({
          wear_status: 'projected',
          projected_km_remaining: '19000',
          projected_wear_date: '2027-01-01',
        }),
      ],
    })
    await show()
    expect(screen.getByText(/~11,806 mi/)).toBeInTheDocument()
  })

  it('gives a null minimum its own wording, not "not enough readings"', async () => {
    respond({ tires: [tire({ wear_status: 'no_minimum_set', min_tread_mm: null })] })
    await show()

    expect(screen.getAllByText(/vehicle\.tires\.actionMinimumTread/).length).toBeGreaterThan(0)
    expect(screen.queryByText(/actionSecondReading/)).toBeNull()
  })
})

describe('TireAnalyticsSection readiness', () => {
  afterEach(() => vi.restoreAllMocks())
  beforeEach(() => respond())

  it('leads with the worn tires, whatever else is missing', async () => {
    // Safety outranks data. A tire at or below its minimum is something to do
    // today; a missing odometer is something to write down.
    respond({
      tires: [tire({ below_threshold: true })],
      readiness: { total: 1, under_minimum: 1, needs_mount_odometer: 9 },
    })
    await show()

    // Scoped to the "Next:" line rather than to the prompt text, which the
    // per-tire table also renders for its own statuses.
    expect(
      screen.getByText(/nextAction: vehicle\.tires\.actionUnderMinimum/)
    ).toBeInTheDocument()
  })

  it('otherwise names the prompt that unblocks the most tires', async () => {
    respond({
      tires: [tire()],
      readiness: { total: 4, needs_second_reading: 1, needs_mount_odometer: 3 },
    })
    await show()

    expect(
      screen.getByText(/nextAction: vehicle\.tires\.actionMountOdometer/)
    ).toBeInTheDocument()
  })

  it('says so when there is nothing left to record', async () => {
    respond({ tires: [tire()], readiness: { total: 1, can_trend: 1, can_project: 1 } })
    await show()
    expect(screen.getByText('vehicle.tires.allAnswered')).toBeInTheDocument()
  })

  it('explains a vehicle with no odometer reading once, not per tire', async () => {
    // B3. An open period's upper bound is the vehicle's latest odometer
    // record, so with none there is no distance for any fitted tire however
    // complete its mount history.
    respond({ tires: [tire(), tire({ id: 2 })], has_odometer_record: false })
    await show()
    expect(screen.getAllByText('vehicle.tires.noOdometerRecord')).toHaveLength(1)
  })
})

describe('TireAnalyticsSection retired tires', () => {
  afterEach(() => vi.restoreAllMocks())
  beforeEach(() => respond())

  it('lists a retired tire and keeps the readiness block about the live ones', async () => {
    // B10. A retired tire's final figures are the most complete data the app
    // will ever hold about it, and it is also the tire nothing can be done
    // about, so it is in the table and out of the counts.
    respond({
      tires: [
        tire({ id: 1, brand: 'Live' }),
        tire({ id: 2, brand: 'Gone', retired_on: '2026-02-01', position: null }),
      ],
      readiness: { total: 1, needs_second_reading: 1 },
    })
    await show()

    expect(screen.getByText(/Gone/)).toBeInTheDocument()
    expect(screen.getByText(/vehicle\.tires\.retiredOn/)).toBeInTheDocument()
    expect(screen.getByText('vehicle.tires.readinessSummary')).toBeInTheDocument()
  })

  it('renders no readiness block when every tire is retired', async () => {
    respond({
      tires: [tire({ retired_on: '2026-02-01' })],
      readiness: { total: 0 },
    })
    await show()

    expect(screen.queryByText('vehicle.tires.readinessTitle')).toBeNull()
    expect(screen.getByText('vehicle.tires.tableTitle')).toBeInTheDocument()
  })
})

describe('TireAnalyticsSection tread trend', () => {
  afterEach(() => vi.restoreAllMocks())
  beforeEach(() => respond())

  it('says there is nothing to plot when no tire has two tread readings', async () => {
    respond({ tires: [tire({ readings: [reading(1, '8.00')] })] })
    await show()
    expect(screen.getByText('vehicle.tires.trendEmpty')).toBeInTheDocument()
  })

  it('plots a tire with two tread readings', async () => {
    respond({ tires: [tire({ readings: [reading(1, '8.00'), reading(2, '7.00')] })] })
    await show()
    expect(screen.queryByText('vehicle.tires.trendEmpty')).toBeNull()
  })

  it('does not plot two pressure-only readings', async () => {
    // Since #152 a reading can carry a pressure and no tread. Two of those are
    // two points on a chart with no y value.
    respond({ tires: [tire({ readings: [reading(1, null), reading(2, null)] })] })
    await show()
    expect(screen.getByText('vehicle.tires.trendEmpty')).toBeInTheDocument()
  })

  it('gives a pressure-only tire no series when another tire does plot', async () => {
    // The test above cannot see this: with NO plottable tire the chart is
    // hidden either way, so dropping the tread filter from the series list
    // survived it. The difference is a legend entry for a tire that draws no
    // line, and it only appears in a mix.
    respond({
      tires: [
        tire({ id: 1, brand: 'Plots', readings: [reading(1, '8.00'), reading(2, '7.00')] }),
        tire({ id: 2, brand: 'Pressure', readings: [reading(1, null), reading(2, null)] }),
      ],
    })
    await show()

    const series = screen.getAllByTestId('series').map((el) => el.textContent)
    expect(series).toEqual(['FL - Plots'])
  })
})

describe('TireAnalyticsSection trend series (G4-22)', () => {
  afterEach(() => vi.restoreAllMocks())
  beforeEach(() => respond())

  /** A stored tire: no position, so its label is "In storage - brand". */
  const stored = (id: number, treads: [string, string], over: Record<string, unknown> = {}) =>
    tire({
      id,
      position: null,
      brand: 'Blizzak',
      readings: [
        { ...reading(1, treads[0]), id: id * 10 + 1, tire_id: id, position: null },
        { ...reading(2, treads[1]), id: id * 10 + 2, tire_id: id, position: null },
      ],
      ...over,
    })

  it('draws four lines for a stored set of four identical tires', async () => {
    // Keyed by label, all four wrote into ONE column, so the set drew as one
    // line carrying whichever tire's tread landed last. Keyed by id, each line
    // reads its own values (imperial, so in32: 8 mm = 10.08, 7 mm = 8.82).
    respond({
      tires: [
        stored(1, ['8.00', '7.00']),
        stored(2, ['7.00', '6.00']),
        stored(3, ['6.00', '5.00']),
        stored(4, ['5.00', '4.00']),
      ],
    })
    await show()

    expect(chart.lines).toHaveLength(4)
    const keys = chart.lines.map((line) => line.dataKey)
    expect(new Set(keys).size).toBe(4)

    const [jan, feb] = chart.data
    expect(jan.date).toBe('2026-01-01')
    expect(feb.date).toBe('2026-02-01')
    const at = (row: Record<string, unknown>) => keys.map((key) => Number(row[key]).toFixed(2))
    expect(at(jan)).toEqual(['10.08', '8.82', '7.56', '6.30'])
    expect(at(feb)).toEqual(['8.82', '7.56', '6.30', '5.04'])
  })

  it('tells clashing tires apart by DOT code when every one has a distinct code', async () => {
    respond({
      tires: [
        stored(2, ['7.00', '6.00'], { dot_code: 'B2 4523' }),
        stored(1, ['8.00', '7.00'], { dot_code: 'A1 0123' }),
      ],
    })
    await show()

    expect(chart.lines.map((line) => line.name)).toEqual([
      'vehicle.tires.inStorage - Blizzak (DOT B2 4523)',
      'vehicle.tires.inStorage - Blizzak (DOT A1 0123)',
    ])
  })

  it('numbers clashing tires by id when a DOT code is missing', async () => {
    // Out of id order on purpose: the plain label goes to the lowest id, not
    // to whichever tire the API happened to list first.
    respond({
      tires: [
        stored(3, ['6.00', '5.00'], { dot_code: 'A' }),
        stored(1, ['8.00', '7.00'], { dot_code: null }),
        stored(2, ['7.00', '6.00'], { dot_code: 'B' }),
      ],
    })
    await show()

    expect(chart.lines.map((line) => line.name)).toEqual([
      'vehicle.tires.inStorage - Blizzak #3',
      'vehicle.tires.inStorage - Blizzak',
      'vehicle.tires.inStorage - Blizzak #2',
    ])
  })

  it('numbers clashing tires when two share a DOT code', async () => {
    respond({
      tires: [
        stored(1, ['8.00', '7.00'], { dot_code: 'SAME' }),
        stored(2, ['7.00', '6.00'], { dot_code: 'SAME' }),
      ],
    })
    await show()

    expect(chart.lines.map((line) => line.name)).toEqual([
      'vehicle.tires.inStorage - Blizzak',
      'vehicle.tires.inStorage - Blizzak #2',
    ])
  })

  it('leaves unique labels alone, DOT code or not', async () => {
    // guard: today's legend text for the common case, where nothing clashes.
    respond({
      tires: [
        tire({ id: 1, position: 'FL', dot_code: 'X1', readings: [reading(1, '8.00'), reading(2, '7.00')] }),
        tire({ id: 2, position: 'FR', dot_code: 'X2', readings: [reading(1, '8.00'), reading(2, '7.00')] }),
      ],
    })
    await show()

    expect(chart.lines.map((line) => line.name)).toEqual(['FL - Michelin', 'FR - Michelin'])
  })
})

describe('TireAnalyticsSection on the hour meter (#217)', () => {
  afterEach(() => vi.restoreAllMocks())

  it('projects in hours, heads the column with hours and explains a missing hour meter reading', async () => {
    apiGet.mockResolvedValue({
      data: {
        readiness: { ...EMPTY_READINESS, total: 1, can_project: 1 },
        usage_axis: 'hours',
        has_usage_record: false,
        has_odometer_record: true,
        tires: [
          tire({
            brand: 'Maxxis',
            tread_depth_mm: '7.00',
            usage_axis: 'hours',
            wear_status: 'projected',
            projected_usage_remaining: '250.0',
            projected_km_remaining: null,
            projected_wear_date: null,
            distance_status: 'complete',
            usage_on_tire: '60.0',
            distance_km: null,
          }),
        ],
      },
    })
    render(<TireAnalyticsSection vin={VIN} />)
    expect(await screen.findByText('~250.0 hr')).toBeInTheDocument()
    expect(screen.getByText('60.0 hr')).toBeInTheDocument()
    expect(screen.getByText('vehicle.tires.colHours')).toBeInTheDocument()
    expect(screen.getByText('vehicle.tires.noHoursRecord')).toBeInTheDocument()
    expect(screen.queryByText('vehicle.tires.noOdometerRecord')).toBeNull()
  })

  it('asks for the hour meter, not the odometer, in the next action and the table', async () => {
    apiGet.mockResolvedValue({
      data: {
        readiness: { ...EMPTY_READINESS, total: 1, needs_reading_usage: 1 },
        usage_axis: 'hours',
        has_usage_record: true,
        has_odometer_record: false,
        tires: [
          tire({ usage_axis: 'hours', wear_status: 'no_reading_odometers', distance_status: 'nothing_bounded' }),
          tire({ id: 2, position: 'FR', usage_axis: 'hours', distance_status: 'incomplete', known_usage: '40.0', known_usage_since: '2026-02-01' }),
        ],
      },
    })
    render(<TireAnalyticsSection vin={VIN} />)
    expect(await screen.findByText(/nextAction: vehicle\.tires\.actionReadingHours/)).toBeInTheDocument()
    expect(screen.getByText(/^40\.0 hr \(/)).toBeInTheDocument()
    expect(screen.getByText('vehicle.tires.actionReadingHours')).toBeInTheDocument()
    expect(screen.getByText('vehicle.tires.actionMountHours')).toBeInTheDocument()
    expect(screen.queryByText(/actionReadingOdometer|actionMountOdometer/)).toBeNull()
    expect(screen.queryByText(/noOdometerRecord|noHoursRecord/)).toBeNull()
  })

  it('counts the tires that can report hours, and distance on a distance vehicle', async () => {
    const summary = (axis: string) => ({
      data: {
        readiness: { ...EMPTY_READINESS, total: 1, can_report_usage: 1 },
        usage_axis: axis,
        has_usage_record: true,
        has_odometer_record: true,
        tires: [tire({ usage_axis: axis })],
      },
    })
    apiGet.mockResolvedValue(summary('hours'))
    const { unmount } = render(<TireAnalyticsSection vin={VIN} />)
    expect(await screen.findByText('vehicle.tires.canReportHours')).toBeInTheDocument()
    expect(screen.queryByText('vehicle.tires.canReportDistance')).toBeNull()
    unmount()

    apiGet.mockResolvedValue(summary('distance'))
    render(<TireAnalyticsSection vin={VIN} />)
    expect(await screen.findByText('vehicle.tires.canReportDistance')).toBeInTheDocument()
    expect(screen.queryByText('vehicle.tires.canReportHours')).toBeNull()
  })
})
