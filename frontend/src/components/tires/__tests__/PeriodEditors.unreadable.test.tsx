/**
 * Both period editors have a mount half and a dismount half with the same
 * fields, so the "enter a valid number" toast has to say which half. It named
 * only "Odometer (km)", while the legends on screen said Mounted and Dismounted.
 * Strings come from the en bundle so the toast's text is real.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'

import { METRIC_UNITS } from '../../../__tests__/factories'

vi.mock('react-i18next', async () => (await import('@/__tests__/i18nEn')).reactI18nextEn())

const mutate = vi.fn()
vi.mock('../../../hooks/queries/useTires', () => ({
  useCreateMountPeriod: () => ({ mutate, isPending: false }),
  useUpdateMountPeriod: () => ({ mutate, isPending: false }),
}))
vi.mock('../../../hooks/queries/useOdometerRecords', () => ({
  useNearestOdometer: () => ({ data: undefined, isSuccess: false }),
}))
vi.mock('../../../hooks/queries/useHoursRecords', () => ({
  useNearestHours: () => ({ data: undefined, isSuccess: false }),
}))
vi.mock('../../../hooks/useUnitPreference', () => {
  const unitPreference = () => ({
    system: 'metric',
    showBoth: false,
    gallonStandard: METRIC_UNITS.secondary_gallon,
    units: METRIC_UNITS,
  })
  return { useUnitPreference: unitPreference, useAccountUnitPreference: unitPreference }
})
const toastError = vi.fn()
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: (...args: unknown[]) => toastError(...args) } }))

import AddPastPeriodDrawer from '../AddPastPeriodDrawer'
import MountPeriodEditor from '../MountPeriodEditor'

const VIN = '1HGCM82633A004352'
const TIRE = { id: 9, vin: VIN, position: 'FL', min_tread_mm: '2.0', below_threshold: false, created_at: '2026-01-01T00:00:00', mount_periods: [], readings: [] }
const CLOSED = { id: 4, position: 'FL', mounted_on: '2026-01-10', dismounted_on: '2026-03-10', mounted_odometer_km: '10000.00', dismounted_odometer_km: '12000.00', is_assumed: false, observed_active_on: null, notes: null }
const labelFor = (p: string | null | undefined) => `pos-${p}`
const input = (id: string) => document.getElementById(id) as HTMLInputElement
const save = () => fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Save' }))

beforeEach(() => {
  mutate.mockReset()
  toastError.mockReset()
})

describe('period editors: an unreadable number says which half it is in', () => {
  it('AddPastPeriodDrawer names the dismount odometer', () => {
    render(<AddPastPeriodDrawer vin={VIN} tire={TIRE as never} open onClose={vi.fn()} labelFor={labelFor} />)
    fireEvent.click(within(screen.getByRole('dialog')).getByText('pos-FR'))
    fireEvent.change(input('past-mount-date'), { target: { value: '2025-06-01' } })
    fireEvent.change(input('past-dismount-date'), { target: { value: '2025-09-01' } })
    fireEvent.change(input('past-mount-odometer'), { target: { value: '1000' } })
    fireEvent.change(input('past-dismount-odometer'), { target: { value: 'abc' } })
    save()
    expect(toastError).toHaveBeenCalledWith('Dismounted / Odometer (km): enter a valid number')
    expect(mutate).not.toHaveBeenCalled()
  })

  it('MountPeriodEditor names the mount odometer', () => {
    render(<MountPeriodEditor vin={VIN} tire={TIRE as never} period={CLOSED as never} open onClose={vi.fn()} labelFor={labelFor} />)
    fireEvent.change(input('period-mount-odometer'), { target: { value: 'abc' } })
    save()
    expect(toastError).toHaveBeenCalledWith('Mounted / Odometer (km): enter a valid number')
    expect(mutate).not.toHaveBeenCalled()
  })
})
