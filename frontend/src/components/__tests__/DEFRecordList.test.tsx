import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import type { DEFRecord } from '../../types/def'

// Mock the DEF query hooks so this stays a unit test — no QueryClient/api wiring.
const useDEFRecordsMock = vi.fn()
const useDEFAnalyticsMock = vi.fn()
const useDeleteDEFRecordMock = vi.fn()

vi.mock('../../hooks/queries/useDEFRecords', () => ({
  useDEFRecords: () => useDEFRecordsMock(),
  useDEFAnalytics: () => useDEFAnalyticsMock(),
  useDeleteDEFRecord: () => useDeleteDEFRecordMock(),
  useCreateDEFRecord: () => ({ mutateAsync: vi.fn() }),
  useUpdateDEFRecord: () => ({ mutateAsync: vi.fn() }),
}))

vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}))

// Same mock pattern as VehicleEditDrawer.test.tsx — these hooks need AuthProvider
// otherwise, and it's not under test here. Mutable so the B7 unit-aware
// volume-header test can toggle metric/imperial; every other test leaves it
// at the metric default restored in afterEach.
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

// LOCAL i18n mock (same pattern as the fuel-list B5 fix): the GLOBAL setup.ts
// mock is `t: (key) => key`, which discards interpolation args, so
// `t('defList.volumeUnit', { unit })` renders the identical string regardless
// of unit — a header test against it can't tell L from gal, or from a dropped
// {{unit}} entirely. This override retains `options.unit` for the volume-header
// assertions and is otherwise behaviour-identical to the global mock (bare key,
// no unit) so the maintained tests stay green.
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
vi.mock('../../hooks/useCurrencyPreference', () => ({
  useCurrencyPreference: () => ({
    currencyCode: 'USD',
    locale: 'en-US',
    formatCurrency: () => '$0.00',
  }),
}))

import { UK_IMPERIAL_UNITS } from '../../__tests__/factories'
import { UnitConverter } from '../../utils/units'
import DEFRecordList from '../DEFRecordList'

const mockRecord: DEFRecord = {
  id: 1,
  vin: 'TEST12345678901234',
  date: '2026-02-10',
  entry_type: 'purchase',
  liters: '20.820',
  odometer_km: '88514',
  fill_level: '1.00',
  cost: '24.75',
  price_per_unit: '1.189',
  source: 'Truck Stop / Station Nozzle',
  brand: 'BlueDEF',
  notes: null,
  origin_fuel_record_id: null,
  created_at: '2026-02-10T14:30:00',
} as DEFRecord

beforeEach(() => {
  vi.clearAllMocks()
  useDEFRecordsMock.mockReturnValue({
    data: { records: [mockRecord] },
    isLoading: false,
    error: null,
  })
  useDEFAnalyticsMock.mockReturnValue({ data: undefined })
  useDeleteDEFRecordMock.mockReturnValue({
    mutate: vi.fn(),
    isPending: false,
    variables: undefined,
  })
})

describe('DEFRecordList — readOnly gating (non-diesel vehicles)', () => {
  it('shows the read-only notice and hides add/edit affordances when readOnly', () => {
    render(<DEFRecordList vin="TEST12345678901234" readOnly />)

    expect(screen.getByText('defList.readOnlyNotice')).toBeInTheDocument()
    expect(screen.queryByText('defList.addDEF')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('common:edit')).not.toBeInTheDocument()
    // Delete stays available so bad legacy data can still be removed.
    expect(screen.getByLabelText('common:delete')).toBeInTheDocument()
  })

  it('hides the "add first record" button in the empty state when readOnly', () => {
    useDEFRecordsMock.mockReturnValue({
      data: { records: [] },
      isLoading: false,
      error: null,
    })

    render(<DEFRecordList vin="TEST12345678901234" readOnly />)

    expect(screen.getByText('defList.readOnlyNotice')).toBeInTheDocument()
    expect(screen.queryByText('defList.addFirstRecord')).not.toBeInTheDocument()
  })

  it('shows add/edit affordances and no notice when not readOnly (diesel)', () => {
    render(<DEFRecordList vin="TEST12345678901234" />)

    expect(screen.queryByText('defList.readOnlyNotice')).not.toBeInTheDocument()
    expect(screen.getByText('defList.addDEF')).toBeInTheDocument()
    expect(screen.getByLabelText('common:edit')).toBeInTheDocument()
    expect(screen.getByLabelText('common:delete')).toBeInTheDocument()
  })
})

describe('DEFRecordList — DataTable structure + unit-aware header (M3/B7)', () => {
  afterEach(() => { unitPrefMock.system = 'metric' })

  it('renders a DataTable whose accessible name IS the translated caption (M3 — proves the hand-rolled <table> → <DataTable> migration landed)', () => {
    render(<DEFRecordList vin="TEST12345678901234" />)
    expect(screen.getByRole('table', { name: 'defList.tableCaption' })).toBeInTheDocument()
  })

  it('interpolates the SYSTEM volume unit into the header — L in metric, gal in imperial (B7) (fails if the impl omits {{unit}}, hardcodes gal for both, or reverts to the static `defList.gallons` key)', () => {
    // getVolumeUnit → 'L' (metric) / 'gal' (imperial); the local mock renders it into the header.
    unitPrefMock.system = 'metric'
    const metric = render(<DEFRecordList vin="TEST12345678901234" />)
    const metricTable = screen.getByRole('table', { name: 'defList.tableCaption' })
    expect(within(metricTable).getByRole('columnheader', { name: 'defList.volumeUnit (L)' })).toBeInTheDocument()
    expect(within(metricTable).queryByRole('columnheader', { name: 'defList.gallons' })).not.toBeInTheDocument()
    metric.unmount()
    unitPrefMock.system = 'imperial'
    render(<DEFRecordList vin="TEST12345678901234" />)
    const imperialTable = screen.getByRole('table', { name: 'defList.tableCaption' })
    expect(within(imperialTable).getByRole('columnheader', { name: 'defList.volumeUnit (gal)' })).toBeInTheDocument()
  })

  it('renders the Type column as a Chip — purchase for a manual record, auto for an auto_fuel_sync record (SDQ-A category chip landed)', () => {
    const { unmount } = render(<DEFRecordList vin="TEST12345678901234" />)
    expect(within(screen.getByRole('table', { name: 'defList.tableCaption' })).getByText('defList.purchase')).toBeInTheDocument()
    unmount()
    useDEFRecordsMock.mockReturnValue({ data: { records: [{ ...mockRecord, id: 2, entry_type: 'auto_fuel_sync' }] }, isLoading: false, error: null })
    render(<DEFRecordList vin="TEST12345678901234" />)
    expect(within(screen.getByRole('table', { name: 'defList.tableCaption' })).getByText('defList.auto')).toBeInTheDocument()
  })

  it('renders Card summary tiles when analytics are present (M3 — a tile label proves the Card+Mono block landed)', () => {
    useDEFAnalyticsMock.mockReturnValue({ data: {
      record_count: 3, total_cost: 74.25, total_liters: 62.4, estimated_km_remaining: 2500,
      estimated_days_remaining: 40, liters_per_1000_km: null, avg_cost_per_liter: null, data_confidence: 'high',
    } })
    render(<DEFRecordList vin="TEST12345678901234" />)
    expect(screen.getByText('defList.totalSpent')).toBeInTheDocument()
  })
})

describe('DEFRecordList — one gallon per page, taken from the user', () => {
  beforeEach(() => {
    UnitConverter.setGallonStandard('us')
    unitPrefMock.system = 'metric'
    unitPrefMock.units = null
    useDEFAnalyticsMock.mockReturnValue({
      data: {
        record_count: 1,
        estimated_km_remaining: null,
        estimated_days_remaining: null,
        liters_per_1000_km: '4.700',
        avg_cost_per_liter: '1.189',
        total_cost: '24.75',
        total_liters: '20.820',
        data_confidence: 'high',
      },
    })
  })
  afterEach(() => {
    unitPrefMock.system = 'metric'
    unitPrefMock.units = null
  })

  it('puts the consumption card, the cost card and the volume total on the imperial gallon', () => {
    UnitConverter.setGallonStandard('us')
    unitPrefMock.system = 'imperial'
    unitPrefMock.units = UK_IMPERIAL_UNITS

    render(<DEFRecordList vin="TEST12345678901234" />)

    // 4.7 L/1000km is 1.7 imperial gal/1000mi (2.0 US ones).
    expect(screen.getByText('1.7')).toBeInTheDocument()
    expect(screen.getByText('gal/1,000 mi')).toBeInTheDocument()
    // $1.189/L is $5.41 per imperial gallon, $4.50 per US one.
    expect(screen.getByText('defList.avgCostPerVolume (gal)')).toBeInTheDocument()
    expect(screen.getByText('$5.41')).toBeInTheDocument()
    // 20.82 L is 4.6 imperial gallons.
    expect(screen.getByText('defList.volumeTotal (4.6 gal)')).toBeInTheDocument()
    // And the row cell agrees with all three.
    expect(within(screen.getByRole('table', { name: 'defList.tableCaption' })).getByText('4.58 gal')).toBeInTheDocument()
    expect(UnitConverter.getGallonStandard()).toBe('us')
  })

  it('stays in litres for a metric set even on a UK-default instance', () => {
    UnitConverter.setGallonStandard('uk')
    render(<DEFRecordList vin="TEST12345678901234" />)

    expect(screen.getByText('4.7')).toBeInTheDocument()
    expect(screen.getByText('L/1,000 km')).toBeInTheDocument()
    expect(screen.getByText('defList.avgCostPerVolume (L)')).toBeInTheDocument()
    expect(screen.getByText('$1.19')).toBeInTheDocument()
    expect(screen.getByText('defList.volumeTotal (20.8 L)')).toBeInTheDocument()
  })
})
