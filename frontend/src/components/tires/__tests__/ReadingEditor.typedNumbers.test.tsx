/**
 * The reading editor's numbers are typed text read in the user's language
 * (G1b-21). They were native number boxes read with Number(), so a German
 * "32,5" psi read as blank and the pressure was dropped on save.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, within } from '@testing-library/react'

import { IMPERIAL_UNITS } from '../../../__tests__/factories'
import { setActiveLocale } from '@/constants/i18n'
import { makeUnitFormat } from '@/utils/unitFormat'

const mutate = vi.fn()
vi.mock('../../../hooks/queries/useTires', () => ({
  useUpdateTireReading: () => ({ mutate, isPending: false }),
}))
vi.mock('../../../hooks/queries/useOdometerRecords', () => ({
  useNearestOdometer: () => ({ data: undefined, isSuccess: false }),
}))
vi.mock('../../../hooks/queries/useHoursRecords', () => ({
  useNearestHours: () => ({ data: undefined, isSuccess: false }),
}))
const toastError = vi.fn()
vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: (...args: unknown[]) => toastError(...args) },
}))
vi.mock('../../../hooks/useUnitPreference', async () => {
  const { IMPERIAL_UNITS: units } = await import('../../../__tests__/factories')
  const unitPreference = () => ({ system: 'imperial', showBoth: false, gallonStandard: 'us', units })
  return { useUnitPreference: unitPreference, useAccountUnitPreference: unitPreference }
})

import ReadingEditor from '../ReadingEditor'

const VIN = '1HGCM82633A004352'
const TIRE = { id: 9, vin: VIN, position: 'FL', min_tread_mm: '1.60', mount_periods: [], readings: [] }
const READING = {
  id: 31,
  tire_id: 9,
  vin: VIN,
  position: 'FL',
  recorded_at: '2026-10-11',
  odometer_km: null,
  engine_hours: null,
  tread_depth_mm: '6.35',
  pressure_kpa: '220.00',
  notes: null,
  created_at: '2026-10-11T12:00:00',
}
const input = (id: string) => document.getElementById(id) as HTMLInputElement
const save = () => fireEvent.click(within(screen.getByRole('dialog')).getByText('common:save'))

const renderEditor = () =>
  render(
    <ReadingEditor
      vin={VIN}
      tire={TIRE as never}
      reading={READING as never}
      open
      onClose={vi.fn()}
      labelFor={(p) => `pos-${p}`}
    />
  )

beforeEach(() => {
  mutate.mockReset()
  toastError.mockReset()
})
afterEach(() => setActiveLocale('en'))

describe('ReadingEditor: numbers read in the user language', () => {
  it('de: a 32,5 psi pressure saves as 32.5 psi in kPa', () => {
    setActiveLocale('de')
    renderEditor()
    fireEvent.change(input('reading-edit-pressure'), { target: { value: '32,5' } })
    save()

    expect(mutate).toHaveBeenCalledTimes(1)
    const expected = makeUnitFormat(IMPERIAL_UNITS).pressure.toCanonical(32.5) ?? Number.NaN
    expect(mutate.mock.calls[0][0].pressure_kpa).toBeCloseTo(expected, 6)
  })

  it('de: a gauge reading of 0.346 in saves as 11/32, not 346/32', () => {
    setActiveLocale('de')
    renderEditor()
    fireEvent.change(input('reading-edit-tread'), { target: { value: '0.346' } })
    save()

    expect(mutate).toHaveBeenCalledTimes(1)
    // 11/32 in, the 32nd the gauge's 0.346 in rounds to.
    expect(mutate.mock.calls[0][0].tread_depth_mm).toBe(8.73125)
  })

  it('refuses text that is not a number instead of clearing the pressure', () => {
    renderEditor()
    fireEvent.change(input('reading-edit-pressure'), { target: { value: 'abc' } })
    save()

    expect(mutate).not.toHaveBeenCalled()
    expect(toastError).toHaveBeenCalledWith('numberInput.invalidField')
  })
})
