import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'

import { IMPERIAL_UNITS, METRIC_UNITS, type UnitSet } from '../../../__tests__/factories'

const useCreateMock = vi.fn()
vi.mock('../../../hooks/queries/useTires', () => ({
  useCreateMountPeriod: () => useCreateMock(),
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

/** Overridden per test; defaults to metric. */
let units: UnitSet = METRIC_UNITS
vi.mock('../../../hooks/useUnitPreference', () => ({
  useUnitPreference: () => ({
    system: units.distance === 'km' ? 'metric' : 'imperial',
    showBoth: false,
    gallonStandard: units.secondary_gallon,
    units,
  }),
}))

const toastSuccess = vi.fn()
const toastError = vi.fn()
vi.mock('sonner', () => ({
  toast: {
    success: (...args: unknown[]) => toastSuccess(...args),
    error: (...args: unknown[]) => toastError(...args),
  },
}))

import AddPastPeriodDrawer from '../AddPastPeriodDrawer'

const VIN = '1HGCM82633A004352'
const TIRE = {
  id: 9,
  vin: VIN,
  position: 'FL',
  min_tread_mm: '2.0',
  below_threshold: false,
  created_at: '2026-01-01T00:00:00',
  mount_periods: [],
  readings: [],
}
const labelFor = (p: string | null | undefined) => `pos-${p}`
const drawer = () => within(screen.getByRole('dialog'))
const input = (id: string) => document.getElementById(id) as HTMLInputElement

describe('AddPastPeriodDrawer', () => {
  const mutate = vi.fn()
  beforeEach(() => {
    mutate.mockReset()
    toastSuccess.mockReset()
    toastError.mockReset()
    useCreateMock.mockReturnValue({ mutate, isPending: false })
    units = METRIC_UNITS
    nearestData = undefined
    nearestSuccess = false
  })

  it('refuses to save without a corner', () => {
    render(<AddPastPeriodDrawer vin={VIN} tire={TIRE as never} open onClose={vi.fn()} labelFor={labelFor} />)
    fireEvent.change(input('past-mount-date'), { target: { value: '2025-06-01' } })
    fireEvent.change(input('past-dismount-date'), { target: { value: '2025-09-01' } })
    fireEvent.click(drawer().getByText('common:save'))
    expect(toastError).toHaveBeenCalledWith('tireList.pastPeriodCornerRequired')
    expect(mutate).not.toHaveBeenCalled()
  })

  it('refuses to save without both dates', () => {
    render(<AddPastPeriodDrawer vin={VIN} tire={TIRE as never} open onClose={vi.fn()} labelFor={labelFor} />)
    fireEvent.click(drawer().getByText('pos-FR'))
    fireEvent.change(input('past-mount-date'), { target: { value: '2025-06-01' } })
    // Dismount date left empty.
    fireEvent.click(drawer().getByText('common:save'))
    expect(toastError).toHaveBeenCalledWith('tireList.pastPeriodDatesRequired')
    expect(mutate).not.toHaveBeenCalled()
  })

  it('sends the corner, both dates and both odometers converted to km', () => {
    units = IMPERIAL_UNITS
    render(<AddPastPeriodDrawer vin={VIN} tire={TIRE as never} open onClose={vi.fn()} labelFor={labelFor} />)
    fireEvent.click(drawer().getByText('pos-FR'))
    fireEvent.change(input('past-mount-date'), { target: { value: '2025-06-01' } })
    fireEvent.change(input('past-dismount-date'), { target: { value: '2025-09-01' } })
    // Typed in miles, deliberately not round numbers so a wrong conversion
    // factor would show. Expected km computed independently below, from the
    // exact mile (1.609344), not by calling anything this test exercises.
    fireEvent.change(input('past-mount-odometer'), { target: { value: '1000.5' } })
    fireEvent.change(input('past-dismount-odometer'), { target: { value: '12345.6' } })
    fireEvent.click(drawer().getByText('common:save'))

    const expectedMountedKm = 1000.5 * 1.609344
    const expectedDismountedKm = 12345.6 * 1.609344
    expect(mutate.mock.calls[0][0]).toEqual({
      tireId: 9,
      position: 'FR',
      mounted_on: '2025-06-01',
      dismounted_on: '2025-09-01',
      mounted_odometer_km: expectedMountedKm,
      dismounted_odometer_km: expectedDismountedKm,
      notes: null,
    })
  })

  it('tapping Use on a suggestion sends its exact canonical value', () => {
    units = IMPERIAL_UNITS
    nearestData = { date: '2026-01-05', odometer_km: '100000.00', source: 'manual', days_away: -5 }
    nearestSuccess = true
    render(<AddPastPeriodDrawer vin={VIN} tire={TIRE as never} open onClose={vi.fn()} labelFor={labelFor} />)
    fireEvent.click(drawer().getByText('pos-FR'))
    fireEvent.change(input('past-mount-date'), { target: { value: '2025-06-01' } })
    fireEvent.change(input('past-dismount-date'), { target: { value: '2025-09-01' } })
    // 100000 km does not survive mile rounding (100000 / 1.609344 -> 62137 mi,
    // and back -> 99999.808128 km), which is the exact shape of the defect
    // MountEventFields's Use control exists to avoid.
    fireEvent.click(within(screen.getByTestId('past-mount-suggestion')).getByText('tireList.suggestionUse'))
    fireEvent.click(drawer().getByText('common:save'))
    expect(mutate.mock.calls[0][0].mounted_odometer_km).toBe(100000)
  })

  it('on an hours-only vehicle records the hour meter and no odometer', () => {
    render(
      <AddPastPeriodDrawer vin={VIN} tire={TIRE as never} open onClose={vi.fn()} labelFor={labelFor} tracksDistance={false} tracksHours />
    )
    fireEvent.click(drawer().getByText('pos-RL'))
    fireEvent.change(input('past-mount-date'), { target: { value: '2025-06-01' } })
    fireEvent.change(input('past-dismount-date'), { target: { value: '2025-09-01' } })
    fireEvent.change(input('past-mount-hours'), { target: { value: '40' } })
    fireEvent.change(input('past-dismount-hours'), { target: { value: '95.5' } })
    fireEvent.click(drawer().getByText('common:save'))
    const payload = mutate.mock.calls[0][0]
    expect(payload.mounted_hours).toBe(40)
    expect(payload.dismounted_hours).toBe(95.5)
    expect(payload).not.toHaveProperty('mounted_odometer_km')
    expect(payload).not.toHaveProperty('dismounted_odometer_km')
  })
})
