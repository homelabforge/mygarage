import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'

import { IMPERIAL_UNITS, METRIC_UNITS, type UnitSet } from '../../../__tests__/factories'

const useUpdateMock = vi.fn()
vi.mock('../../../hooks/queries/useTires', () => ({
  useUpdateMountPeriod: () => useUpdateMock(),
}))

/** Overridden per test; defaults match every pre-existing test's expectation
 *  of no suggestion. */
let nearestData: { date: string; odometer_km: string; source: string; days_away: number } | null | undefined =
  undefined
let nearestSuccess = false
vi.mock('../../../hooks/queries/useOdometerRecords', () => ({
  useNearestOdometer: () => ({ data: nearestData, isSuccess: nearestSuccess }),
}))
vi.mock('../../../hooks/queries/useHoursRecords', () => ({
  useNearestHours: () => ({ data: undefined, isSuccess: false }),
}))

/** Overridden per test; defaults to metric, matching every pre-existing
 *  test's fixed odometers. */
let units: UnitSet = METRIC_UNITS
vi.mock('../../../hooks/useUnitPreference', () => {
  // UnitSession reads the account half too; same answer, nothing to pin here.
  const unitPreference = () => ({
    system: units.distance === 'km' ? 'metric' : 'imperial',
    showBoth: false,
    gallonStandard: units.secondary_gallon,
    units,
  })
  return {
    useUnitPreference: unitPreference,
    useAccountUnitPreference: unitPreference,
  }
})

import MountPeriodEditor from '../MountPeriodEditor'

const VIN = '1HGCM82633A004352'
const TIRE = { id: 9, vin: VIN, position: 'FL', min_tread_mm: '2.0', below_threshold: false, created_at: '2026-01-01T00:00:00', mount_periods: [], readings: [] }
const CLOSED = { id: 4, position: 'FL', mounted_on: '2026-01-10', dismounted_on: '2026-03-10', mounted_odometer_km: '10000.00', dismounted_odometer_km: '12000.00', is_assumed: false, observed_active_on: null, notes: 'first winter' }
const OPEN = { ...CLOSED, id: 5, dismounted_on: null, dismounted_odometer_km: null, notes: null }
const labelFor = (p: string | null | undefined) => `pos-${p}`
const drawer = () => within(screen.getByRole('dialog'))
const input = (id: string) => document.getElementById(id) as HTMLInputElement

describe('MountPeriodEditor', () => {
  const mutate = vi.fn()
  beforeEach(() => {
    mutate.mockReset()
    useUpdateMock.mockReturnValue({ mutate, isPending: false })
    units = METRIC_UNITS
    nearestData = undefined
    nearestSuccess = false
  })

  it('seeds every field from a closed period and sends all five', () => {
    render(<MountPeriodEditor vin={VIN} tire={TIRE as never} period={CLOSED as never} open onClose={vi.fn()} labelFor={labelFor} />)
    expect(input('period-mount-date')).toHaveValue('2026-01-10')
    expect(input('period-mount-odometer')).toHaveValue('10000')
    expect(input('period-dismount-date')).toHaveValue('2026-03-10')
    expect(input('period-dismount-odometer')).toHaveValue('12000')
    expect(input('period-notes')).toHaveValue('first winter')
    fireEvent.change(input('period-mount-odometer'), { target: { value: '10500' } })
    fireEvent.click(drawer().getByText('common:save'))
    expect(mutate.mock.calls[0][0]).toEqual({
      tireId: 9,
      periodId: 4,
      mounted_on: '2026-01-10',
      mounted_odometer_km: 10500,
      dismounted_on: '2026-03-10',
      dismounted_odometer_km: 12000,
      notes: 'first winter',
    })
  })

  it('an open period has no dismount fields and sends none', () => {
    render(<MountPeriodEditor vin={VIN} tire={TIRE as never} period={OPEN as never} open onClose={vi.fn()} labelFor={labelFor} />)
    expect(document.getElementById('period-dismount-date')).toBeNull()
    fireEvent.click(drawer().getByText('common:save'))
    const payload = mutate.mock.calls[0][0]
    expect(payload).not.toHaveProperty('dismounted_on')
    expect(payload).not.toHaveProperty('dismounted_odometer_km')
    expect(payload.notes).toBeNull()
  })

  it('clearing a bound sends null, deliberately', () => {
    render(<MountPeriodEditor vin={VIN} tire={TIRE as never} period={CLOSED as never} open onClose={vi.fn()} labelFor={labelFor} />)
    fireEvent.change(input('period-mount-odometer'), { target: { value: '' } })
    fireEvent.click(drawer().getByText('common:save'))
    expect(mutate.mock.calls[0][0].mounted_odometer_km).toBeNull()
  })

  it('refuses to send a closed period without its dismount date', () => {
    render(<MountPeriodEditor vin={VIN} tire={TIRE as never} period={CLOSED as never} open onClose={vi.fn()} labelFor={labelFor} />)
    fireEvent.change(input('period-dismount-date'), { target: { value: '' } })
    fireEvent.click(drawer().getByText('common:save'))
    expect(mutate).not.toHaveBeenCalled()
  })

  it('an accepted suggestion on imperial units stores the exact value it offered', () => {
    units = IMPERIAL_UNITS
    // The period's own mount odometer (50000 km) is deliberately different
    // from the offered reading (100000 km), so a bug that keeps the OLD
    // origin while the typed string changes to the NEW suggestion cannot
    // coincidentally pass. 100000 km does not survive mile rounding
    // (100000 / 1.609344 -> 62137 mi, and back -> 99999.808128 km), which is
    // the exact shape of the defect this pins.
    const period = { ...CLOSED, id: 7, mounted_odometer_km: '50000.00' }
    nearestData = { date: '2026-01-05', odometer_km: '100000.00', source: 'manual', days_away: -5 }
    nearestSuccess = true
    render(<MountPeriodEditor vin={VIN} tire={TIRE as never} period={period as never} open onClose={vi.fn()} labelFor={labelFor} />)
    // Both halves of a closed period render a suggestion from the same
    // mocked reading, so the Use button is scoped to the mount half.
    fireEvent.click(within(screen.getByTestId('period-mount-suggestion')).getByText('tireList.suggestionUse'))
    fireEvent.click(drawer().getByText('common:save'))
    expect(mutate.mock.calls[0][0].mounted_odometer_km).toBe(100000)
  })

  it('an untouched odometer on imperial units still sends the period\'s exact stored value on a notes-only save', () => {
    units = IMPERIAL_UNITS
    // 100000 km does not survive mile rounding either, so this proves the
    // untouched-field path keeps returning the seeded canonical rather than
    // reconverting the rounded display -- the refactor must not regress it.
    const period = { ...CLOSED, id: 8, mounted_odometer_km: '100000.00' }
    render(<MountPeriodEditor vin={VIN} tire={TIRE as never} period={period as never} open onClose={vi.fn()} labelFor={labelFor} />)
    fireEvent.change(input('period-notes'), { target: { value: 'rotated in' } })
    fireEvent.click(drawer().getByText('common:save'))
    expect(mutate.mock.calls[0][0].mounted_odometer_km).toBe(100000)
  })

  it('on an hours-only vehicle edits the hour meter and sends only hours', () => {
    const HOURS_CLOSED = { ...CLOSED, mounted_odometer_km: null, dismounted_odometer_km: null, mounted_hours: '100.0', dismounted_hours: '150.0' }
    render(
      <MountPeriodEditor vin={VIN} tire={TIRE as never} period={HOURS_CLOSED as never} open onClose={vi.fn()} labelFor={labelFor} tracksDistance={false} tracksHours />
    )
    expect(document.getElementById('period-mount-odometer')).toBeNull()
    expect(input('period-mount-hours')).toHaveValue('100.0')
    fireEvent.change(input('period-dismount-hours'), { target: { value: '155' } })
    fireEvent.click(drawer().getByText('common:save'))
    expect(mutate.mock.calls[0][0]).toEqual({
      tireId: 9,
      periodId: 4,
      mounted_on: '2026-01-10',
      mounted_hours: 100,
      dismounted_on: '2026-03-10',
      dismounted_hours: 155,
      notes: 'first winter',
    })
  })
})
