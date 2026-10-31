import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, within } from '@testing-library/react'

import { IMPERIAL_UNITS, METRIC_UNITS, type UnitSet } from '../../../__tests__/factories'

const useUpdateMock = vi.fn()
vi.mock('../../../hooks/queries/useTires', () => ({
  useUpdateTireReading: () => useUpdateMock(),
}))
vi.mock('../../../hooks/queries/useOdometerRecords', () => ({
  useNearestOdometer: () => ({ data: undefined, isSuccess: false }),
}))
vi.mock('../../../hooks/queries/useHoursRecords', () => ({
  useNearestHours: () => ({ data: undefined, isSuccess: false }),
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

/** Overridden per test; metric unless a test says otherwise. */
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

import ReadingEditor from '../ReadingEditor'

const VIN = '1HGCM82633A004352'
const TIRE = {
  id: 9,
  vin: VIN,
  position: 'FL',
  min_tread_mm: '1.60',
  below_threshold: true,
  created_at: '2026-01-01T00:00:00',
  mount_periods: [],
  readings: [],
}
/** The report's reading: 0.346 typed into the 32nds field, stored as 0.27 mm. */
const TYPO = {
  id: 31,
  tire_id: 9,
  vin: VIN,
  position: 'FL',
  recorded_at: '2026-10-11',
  odometer_km: null,
  engine_hours: null,
  tread_depth_mm: '0.27',
  pressure_kpa: '448.00',
  notes: null,
  created_at: '2026-10-11T12:00:00',
}
const onClose = vi.fn()
const labelFor = (p: string | null | undefined): string => `pos-${p}`
const drawer = () => within(screen.getByRole('dialog'))
const input = (id: string) => document.getElementById(id) as HTMLInputElement
const renderEditor = (
  reading: Record<string, unknown> = TYPO,
  flags: { tracksDistance?: boolean; tracksHours?: boolean } = {}
) =>
  render(
    <ReadingEditor
      vin={VIN}
      tire={TIRE as never}
      reading={reading as never}
      open
      onClose={onClose}
      labelFor={labelFor}
      {...flags}
    />
  )

describe('ReadingEditor', () => {
  const mutate = vi.fn()
  beforeEach(() => {
    mutate.mockReset()
    toastSuccess.mockReset()
    toastError.mockReset()
    onClose.mockReset()
    useUpdateMock.mockReturnValue({ mutate, isPending: false })
    units = METRIC_UNITS
  })

  it('seeds every field from the reading and sends them all back', () => {
    renderEditor({ ...TYPO, odometer_km: '15000.00', notes: 'cold morning' })
    expect(input('reading-edit-date')).toHaveValue('2026-10-11')
    expect(input('reading-edit-odometer')).toHaveValue(15000)
    expect(input('reading-edit-tread')).toHaveValue(0.27)
    expect(input('reading-edit-pressure')).toHaveValue(448)
    expect(input('reading-edit-notes')).toHaveValue('cold morning')

    fireEvent.change(input('reading-edit-tread'), { target: { value: '8.73' } })
    fireEvent.click(drawer().getByText('common:save'))

    expect(mutate.mock.calls[0][0]).toEqual({
      tireId: 9,
      readingId: 31,
      recorded_at: '2026-10-11',
      odometer_km: 15000,
      tread_depth_mm: 8.73,
      pressure_kpa: 448,
      notes: 'cold morning',
    })
  })

  it('adds an odometer to a reading logged without one', () => {
    renderEditor()
    expect(input('reading-edit-odometer')).toHaveValue(null)
    fireEvent.change(input('reading-edit-odometer'), { target: { value: '15000' } })
    fireEvent.click(drawer().getByText('common:save'))
    expect(mutate.mock.calls[0][0].odometer_km).toBe(15000)
  })

  it('closes and says so on success, and names the action on a failure', () => {
    renderEditor()
    fireEvent.click(drawer().getByText('common:save'))
    const callbacks = mutate.mock.calls[0][1]
    callbacks.onSuccess()
    expect(toastSuccess).toHaveBeenCalledWith('tireList.readingUpdated')
    expect(onClose).toHaveBeenCalledTimes(1)
    const failure = new Error('409')
    getActionErrorMessageMock.mockReturnValue('the sentence the server sent')
    callbacks.onError(failure)
    expect(getActionErrorMessageMock).toHaveBeenCalledWith(failure, 'tireList.readingUpdateAction')
    expect(toastError).toHaveBeenCalledWith('the sentence the server sent')
  })

  it('refuses a reading left measuring nothing, and sends nothing', () => {
    renderEditor()
    fireEvent.change(input('reading-edit-tread'), { target: { value: '' } })
    fireEvent.change(input('reading-edit-pressure'), { target: { value: '' } })
    fireEvent.click(drawer().getByText('common:save'))
    expect(toastError).toHaveBeenCalledWith('tireList.treadOrPressureRequired')
    expect(mutate).not.toHaveBeenCalled()
  })

  it("refuses a cleared date with the dialogs' date toast, and sends nothing", () => {
    renderEditor()
    fireEvent.change(input('reading-edit-date'), { target: { value: '' } })
    fireEvent.click(drawer().getByText('common:save'))
    expect(toastError).toHaveBeenCalledWith('tireList.eventDateRequired')
    expect(mutate).not.toHaveBeenCalled()
  })

  describe('in 32nds of an inch', () => {
    beforeEach(() => {
      units = IMPERIAL_UNITS
    })

    it('reads a gauge decimal saved without leaving the field as inches', () => {
      renderEditor()
      fireEvent.change(input('reading-edit-tread'), { target: { value: '.346' } })
      fireEvent.click(drawer().getByText('common:save'))
      // 11/32 in, not 0.346/32 in: 11 x 25.4 / 32.
      expect(mutate.mock.calls[0][0].tread_depth_mm).toBe(8.73125)
    })

    it('rewrites the field on blur and says what it converted', () => {
      renderEditor()
      expect(drawer().queryByText('tireList.treadConverted')).toBeNull()
      fireEvent.change(input('reading-edit-tread'), { target: { value: '.346' } })
      fireEvent.blur(input('reading-edit-tread'))
      expect(input('reading-edit-tread')).toHaveValue(11)
      expect(drawer().getByText('tireList.treadConverted')).toBeInTheDocument()
    })

    /** 8.40 mm seeds the field as 11, the 32nd a gauge's 0.346 in rounds to. */
    const GAUGED = { ...TYPO, tread_depth_mm: '8.40' }

    it.each([false, true])(
      'stores a gauge decimal that lands on the seeded 32nd as the new reading (blur: %s)',
      (blur) => {
        renderEditor(GAUGED)
        expect(input('reading-edit-tread')).toHaveValue(11)
        fireEvent.change(input('reading-edit-tread'), { target: { value: '0.346' } })
        if (blur) fireEvent.blur(input('reading-edit-tread'))
        fireEvent.click(drawer().getByText('common:save'))
        // Not the 8.40 the field was seeded with.
        expect(mutate.mock.calls[0][0].tread_depth_mm).toBe(8.73125)
      }
    )

    it('sends an untouched 8.40 back exactly', () => {
      renderEditor(GAUGED)
      fireEvent.click(drawer().getByText('common:save'))
      expect(mutate.mock.calls[0][0].tread_depth_mm).toBe(8.4)
    })

    it('sends an untouched pressure back exactly, not a rounded round trip', () => {
      renderEditor()
      // 448 kPa reads 65.0 PSI; 65.0 PSI converted back is 448.16 kPa.
      expect(input('reading-edit-pressure')).toHaveValue(65)
      fireEvent.change(input('reading-edit-tread'), { target: { value: '11' } })
      fireEvent.click(drawer().getByText('common:save'))
      expect(mutate.mock.calls[0][0].pressure_kpa).toBe(448)
    })
  })

  describe("on the vehicle's own axes (#217)", () => {
    it('an hours-only vehicle edits the hour meter and never sends a junk odometer', () => {
      renderEditor({ ...TYPO, odometer_km: '170.00', engine_hours: '150.0' }, { tracksDistance: false, tracksHours: true })
      expect(input('reading-edit-odometer')).toBeNull()
      expect(input('reading-edit-hours')).toHaveValue(150)
      fireEvent.change(input('reading-edit-hours'), { target: { value: '155' } })
      fireEvent.click(drawer().getByText('common:save'))
      const payload = mutate.mock.calls[0][0]
      expect(payload.engine_hours).toBe(155)
      expect(payload).not.toHaveProperty('odometer_km')
    })

    it('a dual vehicle sends both, an untouched odometer exactly as stored', () => {
      // In miles, where 15,000 km shows as 9321 and only the origin gets 15000 back.
      units = IMPERIAL_UNITS
      renderEditor({ ...TYPO, odometer_km: '15000.00', engine_hours: '150.0' }, { tracksDistance: true, tracksHours: true })
      fireEvent.change(input('reading-edit-hours'), { target: { value: '' } })
      fireEvent.click(drawer().getByText('common:save'))
      const payload = mutate.mock.calls[0][0]
      expect(payload.odometer_km).toBe(15000)
      expect(payload.engine_hours).toBeNull()
    })

    it('a distance-only vehicle sends no hours key, whatever the reading holds', () => {
      renderEditor({ ...TYPO, engine_hours: '150.0' })
      expect(input('reading-edit-hours')).toBeNull()
      fireEvent.click(drawer().getByText('common:save'))
      expect(mutate.mock.calls[0][0]).not.toHaveProperty('engine_hours')
    })
  })
})
