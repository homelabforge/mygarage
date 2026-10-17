/**
 * #217 in the history drawer: an hours tire's bounds, readings and badges run
 * on the hour meter, and a period that only has the other axis's figure gets a
 * line saying what to add.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type React from 'react'
import { fireEvent, render, screen, within } from '@testing-library/react'

const useDeleteReadingMock = vi.fn()
vi.mock('../../../hooks/queries/useTires', () => ({
  useDeleteTireReading: () => useDeleteReadingMock(),
}))

const getActionErrorMessageMock = vi.fn()
vi.mock('../../../utils/httpErrorHandler', () => ({
  getActionErrorMessage: (...args: unknown[]) => getActionErrorMessageMock(...args),
}))

const toastSuccess = vi.fn()
const toastError = vi.fn()
vi.mock('sonner', () => ({
  toast: {
    success: (...args: unknown[]) => toastSuccess(...args),
    error: (...args: unknown[]) => toastError(...args),
  },
}))

vi.mock('../../../hooks/useUnitPreference', () => ({
  useUnitPreference: () => ({
    system: 'metric',
    showBoth: false,
    gallonStandard: 'us',
    units: {
      consumption: 'l_100km',
      distance: 'km',
      length: 'm',
      mass: 'kg',
      pressure: 'kpa',
      secondary_gallon: 'us',
      speed: 'kmh',
      temperature: 'c',
      torque: 'nm',
      tread: 'mm',
      volume: 'L',
    },
  }),
}))

/* The bounds reach the page through t('tireList.periodSince', { from }), and
   the global mock drops the values, so this one shows them. */
const i18n = vi.hoisted(() => ({
  t: (key: string, params?: Record<string, unknown>): string =>
    params ? `${key}|${Object.values(params).join('|')}` : key,
}))
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: i18n.t, i18n: { language: 'en', changeLanguage: () => Promise.resolve() } }),
  Trans: ({ children }: { children: React.ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: () => {} },
}))

import TireHistoryDrawer, { needsReading } from '../TireHistoryDrawer'

const VIN = '1HGCM82633A004352'
const labelFor = (p: string | null | undefined) => (p == null ? 'stored' : `pos-${p}`)
const period = (overrides: Record<string, unknown> = {}) => ({
  id: 2,
  position: 'FL',
  mounted_on: '2026-01-15',
  dismounted_on: null,
  mounted_odometer_km: null,
  dismounted_odometer_km: null,
  mounted_hours: '120.0',
  dismounted_hours: null,
  is_assumed: false,
  observed_active_on: null,
  notes: null,
  ...overrides,
})
const hoursTire = (overrides: Record<string, unknown> = {}) => ({
  id: 9, vin: VIN, position: 'FL', brand: 'Maxxis', min_tread_mm: '2.0', below_threshold: false,
  installed_date: '2026-01-15', usage_axis: 'hours', blocking_period_ids: [], history_faults: [],
  mount_periods: [period()],
  readings: [
    { id: 31, tire_id: 9, vin: VIN, position: 'FL', recorded_at: '2026-02-01', odometer_km: null, engine_hours: '150.0', tread_depth_mm: '7.00', pressure_kpa: null, notes: null, created_at: '2026-02-01T00:00:00' },
  ],
  ...overrides,
})
const show = (tire: unknown, flags = { tracksDistance: false, tracksHours: true }) =>
  render(
    <TireHistoryDrawer vin={VIN} tire={tire as never} open onClose={vi.fn()} onEditPeriod={vi.fn()} onEditReading={vi.fn()} onAddPeriod={vi.fn()} labelFor={labelFor} {...flags} />
  )

describe('TireHistoryDrawer on the hour meter (#217)', () => {
  beforeEach(() => {
    useDeleteReadingMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
  })

  it('bounds a period by its hours, not its odometer', () => {
    show(hoursTire())
    expect(screen.getByTestId('period-2')).toHaveTextContent('120.0 hr')
    expect(screen.getByTestId('period-2')).not.toHaveTextContent('tireList.odometerUnknown')
  })

  it('names the first installation in hours', () => {
    show(hoursTire())
    const line = screen.getByText(/^tireList\.firstInstalled\|/)
    expect(line).toHaveTextContent('120.0 hr')
    expect(line).not.toHaveTextContent('tireList.odometerUnknown')
  })

  it("lists a reading's hours and no odometer row", () => {
    show(hoursTire())
    const row = screen.getByTestId('reading-31')
    expect(row).toHaveTextContent('150.0 hr')
    expect(within(row).queryByText('tireList.odometer')).toBeNull()
  })

  it('badges a period missing its hours as needing the hour meter', () => {
    show(hoursTire({ blocking_period_ids: [2], mount_periods: [period({ mounted_hours: null })] }))
    expect(screen.getByText('tireList.periodNeedsHours')).toBeInTheDocument()
  })

  it('a blocking period with its hours is a fault, not a gap', () => {
    // No odometer either way, so this only passes if the badge reads the hours.
    show(hoursTire({ blocking_period_ids: [2] }))
    expect(screen.getByText('tireList.periodCheck')).toBeInTheDocument()
    expect(screen.queryByText('tireList.periodNeedsHours')).toBeNull()
  })

  it('explains a switched axis', () => {
    show(hoursTire({ mount_periods: [period({ mounted_hours: null, mounted_odometer_km: '1000.00' })] }))
    expect(screen.getByText('tireList.axisNeedsHours')).toBeInTheDocument()
  })

  it('says nothing about the axis when every period has its hours', () => {
    show(hoursTire())
    expect(screen.queryByText('tireList.axisNeedsHours')).toBeNull()
    expect(screen.queryByText('tireList.axisNeedsOdometer')).toBeNull()
  })

  it('a dual vehicle shows both figures on a bound', () => {
    show(
      hoursTire({ usage_axis: 'distance', mount_periods: [period({ mounted_odometer_km: '1000.00' })] }),
      { tracksDistance: true, tracksHours: true }
    )
    expect(screen.getByTestId('period-2')).toHaveTextContent(/1,000 km · 120\.0 hr/)
  })

  it('Edit hands an hours reading to the caller', () => {
    const onEditReading = vi.fn()
    render(
      <TireHistoryDrawer vin={VIN} tire={hoursTire() as never} open onClose={vi.fn()} onEditPeriod={vi.fn()} onEditReading={onEditReading} onAddPeriod={vi.fn()} labelFor={labelFor} tracksDistance={false} tracksHours />
    )
    expect(onEditReading).not.toHaveBeenCalled()
    fireEvent.click(within(screen.getByTestId('reading-31')).getByRole('button', { name: /^tireList\.readingEditLabel/ }))
    expect(onEditReading.mock.calls[0][0]).toMatchObject({ id: 31, engine_hours: '150.0' })
  })
})

describe('needsReading', () => {
  it('reads the axis it is given', () => {
    const p = period({ mounted_hours: null, mounted_odometer_km: '1000.00' }) as never
    expect(needsReading(p, 'hours')).toBe(true)
    expect(needsReading(p, 'distance')).toBe(false)
  })
})
