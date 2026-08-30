import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, within, fireEvent } from '@testing-library/react'
import type { FuelRecord } from '../../types/fuel'

const usePropaneRecordsMock = vi.fn()
const useDeletePropaneRecordMock = vi.fn()
const deleteMutate = vi.fn()

vi.mock('../../hooks/queries/usePropaneRecords', () => ({
  usePropaneRecords: () => usePropaneRecordsMock(),
  useDeletePropaneRecord: () => useDeletePropaneRecordMock(),
  useCreatePropaneRecord: () => ({ mutateAsync: vi.fn() }),
  useUpdatePropaneRecord: () => ({ mutateAsync: vi.fn() }),
}))
vi.mock('@tanstack/react-query', () => ({ useQueryClient: () => ({ invalidateQueries: vi.fn() }) }))
// Mutable unit mock so one test can render imperial (B7 header coverage).
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
// LOCAL i18n mock (B5) — overrides the global setup mock FOR THIS FILE ONLY. For a `{ unit }`
// call it appends the unit so the volume header reflects {{unit}} (the only way this file can
// tell L from gal — the global mock swallows interpolation); every other call returns the bare
// key, so the drawer-title / vendor / action assertions below are unaffected.
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
  useCurrencyPreference: () => ({ currencyCode: 'USD', locale: 'en-US' }),
}))
// PropaneRecordForm (rendered on Add/Edit) → CurrencyInputPrefix → useCurrencySymbol.
vi.mock('../../hooks/useCurrencySymbol', () => ({ useCurrencySymbol: () => '$' }))

import { UK_IMPERIAL_UNITS } from '../../__tests__/factories'
import { UnitConverter } from '../../utils/units'
import PropaneRecordList from '../PropaneRecordList'

// NOTE: the component imports formatCurrency from utils/formatUtils (NOT the currency
// hook), so the REAL formatter runs — formatCurrency(30.44) → "$30.44", never "$0.00".
const record = {
  id: 1,
  vin: 'TEST12345678901234',
  date: '2026-03-01',
  propane_liters: '39.750',
  price_per_unit: '0.766',
  price_basis: 'per_volume',
  cost: '30.44',
  notes: 'Vendor: AmeriGas\nfull tank',
} as FuelRecord

const table = () => screen.getByRole('table', { name: 'propaneList.tableCaption' })

beforeEach(() => {
  vi.clearAllMocks()
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  usePropaneRecordsMock.mockReturnValue({ data: { records: [record] }, isLoading: false, error: null })
  useDeletePropaneRecordMock.mockReturnValue({ mutate: deleteMutate, isPending: false, variables: undefined })
})
afterEach(() => { unitPrefMock.system = 'metric'; unitPrefMock.units = null })

describe('PropaneRecordList — DataTable rows scoped to the named table', () => {
  it('renders the row vendor (parsed from notes) and the row cost INSIDE the table (fails if the vendor or cost column is dropped; scoping stops the Total-Spent tile from satisfying the cost check)', () => {
    render(<PropaneRecordList vin="TEST12345678901234" />)
    expect(within(table()).getByText('AmeriGas')).toBeInTheDocument()
    // formatCurrency(30.44) → "$30.44"; the Total-Spent tile shows it too but lives OUTSIDE the table.
    expect(within(table()).getByText(/30\.44/)).toBeInTheDocument()
  })

  it('interpolates the SYSTEM volume unit into the header — L in metric, gal in imperial (B7) (fails if the impl omits {{unit}}, hardcodes gal for both, or reverts to the static `propaneList.gallons` key)', () => {
    // The local i18n mock retains {{unit}}; getVolumeUnit → 'L' (metric) / 'gal' (imperial).
    unitPrefMock.system = 'metric'
    const metric = render(<PropaneRecordList vin="TEST12345678901234" />)
    expect(within(table()).getByRole('columnheader', { name: 'propaneList.volumeUnit (L)' })).toBeInTheDocument()
    expect(within(table()).queryByRole('columnheader', { name: 'propaneList.gallons' })).not.toBeInTheDocument()
    metric.unmount()
    unitPrefMock.system = 'imperial'
    render(<PropaneRecordList vin="TEST12345678901234" />)
    expect(within(table()).getByRole('columnheader', { name: 'propaneList.volumeUnit (gal)' })).toBeInTheDocument()
  })

  it('interpolates the same unit into the TOTALS caption, which used to be a raw token branch', () => {
    // `units.volume === 'L' ? t('propaneList.totalLiters') : t('propaneList.totalGallons')`
    // was a second vocabulary of unit names in PROSE, one the units gate reports
    // under its token-branch leg and one that could disagree with the header
    // three lines up. It is now the same `{{unit}}` interpolation the header
    // uses, off the same `getVolumeUnit(units)`.
    unitPrefMock.system = 'metric'
    const metric = render(<PropaneRecordList vin="TEST12345678901234" />)
    expect(screen.getByText('propaneList.totalVolume (L)')).toBeInTheDocument()
    expect(screen.queryByText('propaneList.totalLiters')).not.toBeInTheDocument()
    metric.unmount()
    unitPrefMock.system = 'imperial'
    render(<PropaneRecordList vin="TEST12345678901234" />)
    expect(screen.getByText('propaneList.totalVolume (gal)')).toBeInTheDocument()
    expect(screen.queryByText('propaneList.totalGallons')).not.toBeInTheDocument()
  })
})

describe('PropaneRecordList — actions open the right form + fire the mutation', () => {
  it('clicking the header Add opens the CREATE drawer (fails if Add is unwired or opens edit)', () => {
    render(<PropaneRecordList vin="TEST12345678901234" />)
    fireEvent.click(screen.getByRole('button', { name: 'propaneList.addPropane' }))
    expect(screen.getByText('propane.createTitle')).toBeInTheDocument()
    expect(screen.queryByText('propane.editTitle')).not.toBeInTheDocument()
  })

  it('clicking a row Edit opens the EDIT drawer (fails if edit is unwired or opens create)', () => {
    render(<PropaneRecordList vin="TEST12345678901234" />)
    fireEvent.click(within(table()).getByRole('button', { name: 'common:edit' }))
    expect(screen.getByText('propane.editTitle')).toBeInTheDocument()
    expect(screen.queryByText('propane.createTitle')).not.toBeInTheDocument()
  })

  it('clicking a row Delete (confirm accepted) calls the delete mutation with THAT record id (fails if delete is unwired or the confirm gate is dropped)', () => {
    render(<PropaneRecordList vin="TEST12345678901234" />)
    fireEvent.click(within(table()).getByRole('button', { name: 'common:delete' }))
    expect(window.confirm).toHaveBeenCalled()
    expect(deleteMutate).toHaveBeenCalledWith(1, expect.anything())
  })
})

describe('PropaneRecordList — empty state CTA is wired', () => {
  it('shows the empty state and its add-first CTA opens the CREATE drawer (fails if the CTA is unwired or the title text changes)', () => {
    usePropaneRecordsMock.mockReturnValue({ data: { records: [] }, isLoading: false, error: null })
    render(<PropaneRecordList vin="TEST12345678901234" />)
    expect(screen.getByText('propaneList.noRecords')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'propaneList.addFirstRecord' }))
    expect(screen.getByText('propane.createTitle')).toBeInTheDocument()
  })
})

describe('PropaneRecordList — one gallon per page, taken from the user', () => {
  beforeEach(() => {
    UnitConverter.setGallonStandard('us')
    unitPrefMock.units = null
  })

  it('puts the header, the volume cell, the price cell and both cards on the imperial gallon', () => {
    UnitConverter.setGallonStandard('us')
    unitPrefMock.system = 'imperial'
    unitPrefMock.units = UK_IMPERIAL_UNITS

    render(<PropaneRecordList vin="TEST12345678901234" />)

    // 39.75 L is 8.74 imperial gallons (10.50 US ones).
    expect(within(table()).getByRole('columnheader', { name: 'propaneList.volumeUnit (gal)' })).toBeInTheDocument()
    expect(within(table()).getByText('8.74 gal')).toBeInTheDocument()
    // $0.766/L is $3.48 per imperial gallon, $2.90 per US one.
    expect(within(table()).getByText('$3.48')).toBeInTheDocument()
    // The total tile and its label follow the same token.
    expect(screen.getByText('propaneList.totalVolume (gal)')).toBeInTheDocument()
    expect(screen.getByText('8.7 gal')).toBeInTheDocument()
    expect(screen.getByText('propaneList.avgCostPerVolume (gal)')).toBeInTheDocument()
    expect(UnitConverter.getGallonStandard()).toBe('us')
  })

  it('stays in litres for a metric set even on a UK-default instance', () => {
    UnitConverter.setGallonStandard('uk')
    unitPrefMock.system = 'metric'

    render(<PropaneRecordList vin="TEST12345678901234" />)

    expect(within(table()).getByRole('columnheader', { name: 'propaneList.volumeUnit (L)' })).toBeInTheDocument()
    expect(within(table()).getByText('39.75 L')).toBeInTheDocument()
    expect(screen.getByText('propaneList.totalVolume (L)')).toBeInTheDocument()
    expect(screen.getByText('39.8 L')).toBeInTheDocument()
    expect(screen.getByText('propaneList.avgCostPerVolume (L)')).toBeInTheDocument()
  })
})
