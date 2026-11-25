/**
 * Log Reading takes notes like the history editor does (TR L-5): trimmed on
 * the way out, blank sends null, and a reopened drawer starts empty.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'

const useTiresMock = vi.fn()
const writeMock = vi.fn()
const useAddTireReadingMock = vi.fn()
const useTireSetsMock = vi.fn()
const useUpdateTireReadingMock = vi.fn()

vi.mock('../../hooks/queries/useTires', () => ({
  useTires: () => useTiresMock(),
  useCreateAndMountTire: () => writeMock(),
  useCreateTire: () => writeMock(),
  useUpdateTire: () => writeMock(),
  useMountTire: () => writeMock(),
  useDismountTire: () => writeMock(),
  useRestoreTire: () => writeMock(),
  useRetireTire: () => writeMock(),
  useRotateTires: () => writeMock(),
  useAddTireReading: () => useAddTireReadingMock(),
  useDeleteTire: () => writeMock(),
  useDeleteTireReading: () => ({ mutate: vi.fn(), isPending: false }),
  useUpdateTireReading: () => useUpdateTireReadingMock(),
  useTireSets: () => useTireSetsMock(),
  useCreateTireSet: () => writeMock(),
  useUpdateTireSet: () => writeMock(),
  useDeleteTireSet: () => writeMock(),
  useMountTireSet: () => writeMock(),
}))
vi.mock('../../hooks/queries/useOdometerRecords', () => ({
  useNearestOdometer: () => ({ data: undefined, isSuccess: false }),
}))
vi.mock('../../hooks/queries/useHoursRecords', () => ({
  useNearestHours: () => ({ data: undefined, isSuccess: false }),
}))
vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}))
const toastError = vi.fn()
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: (...a: unknown[]) => toastError(...a) } }))
vi.mock('../../hooks/useUnitPreference', () => {
  // UnitSession reads the account half too; same answer, nothing to pin here.
  const unitPreference = () => ({
    system: 'imperial',
    showBoth: false,
    gallonStandard: 'us',
    units: {
      distance: 'mi', speed: 'mph', length: 'ft', volume: 'gal_us', consumption: 'mpg_us',
      pressure: 'psi', temperature: 'f', mass: 'lb', torque: 'lbft', tread: 'in32', secondary_gallon: 'us',
    },
  })
  return {
    useUnitPreference: unitPreference,
    useAccountUnitPreference: unitPreference,
  }
})

import TireList from '../TireList'
import { FOUR_LAYOUT } from '../../__tests__/factories'
import { withConfirm } from '../../__tests__/confirmHelpers'

const VIN = '1HGCM82633A004352'
const HOURS = { usage_axis: 'hours', tracks_distance: false, tracks_hours: true }

const tire = (id: number, position: string | null) => ({
  id, vin: VIN, position, brand: `Tire ${id}`, model_name: null, size: null, dot_code: null,
  tread_depth_mm: '7.00', pressure_kpa: null, min_tread_mm: '2.00', notes: null, storage_location: null,
  set_id: position == null ? 7 : null, retired_on: null, below_threshold: false,
  usage_axis: 'distance', wear_status: 'insufficient_readings', distance_status: 'nothing_bounded',
  blocking_period_ids: [], history_faults: [], readings: [],
  mount_periods: position == null ? [] : [{
    id: id * 10, position, mounted_on: '2026-06-01', dismounted_on: null,
    mounted_odometer_km: null, dismounted_odometer_km: null, mounted_hours: null, dismounted_hours: null,
    is_assumed: false, observed_active_on: null, notes: null,
  }],
})

const list = (tires: unknown[], flags: Record<string, unknown> = {}) =>
  useTiresMock.mockReturnValue({ data: { tires, total: tires.length, ...FOUR_LAYOUT, ...flags }, isLoading: false, error: null })
const dialog = () => within(screen.getByRole('dialog'))
const field = (id: string) => document.getElementById(id) as HTMLInputElement

describe('Log Reading notes (TR L-5)', () => {
  const addReading = vi.fn()
  beforeEach(() => {
    addReading.mockReset()
    toastError.mockReset()
    writeMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useAddTireReadingMock.mockReturnValue({ mutate: addReading, isPending: false })
    useUpdateTireReadingMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useTireSetsMock.mockReturnValue({ data: { sets: [], total: 0 }, isLoading: false, error: null })
  })

  const openAndFill = () => {
    fireEvent.click(screen.getByText('tireList.addReading'))
    fireEvent.change(field('reading-tread'), { target: { value: '8' } })
  }

  it.each([
    ['a distance-only vehicle', {}],
    ['an hours-tracking vehicle', HOURS],
  ])('sends the typed notes, trimmed, on %s', (_name, flags) => {
    list([tire(1, 'FL')], flags)
    render(<TireList vin={VIN} />, { wrapper: withConfirm })
    openAndFill()
    fireEvent.change(dialog().getByLabelText('tireList.notes'), { target: { value: '  inner edge wearing  ' } })
    fireEvent.click(dialog().getByText('common:save'))
    expect(toastError).not.toHaveBeenCalled()
    expect(addReading).toHaveBeenCalledTimes(1)
    expect(addReading.mock.calls[0][0].notes).toBe('inner edge wearing')
  })

  it('blank notes send null', () => {
    list([tire(1, 'FL')])
    render(<TireList vin={VIN} />, { wrapper: withConfirm })
    openAndFill()
    fireEvent.change(dialog().getByLabelText('tireList.notes'), { target: { value: '   ' } })
    fireEvent.click(dialog().getByText('common:save'))
    expect(addReading).toHaveBeenCalledTimes(1)
    expect(addReading.mock.calls[0][0].notes).toBeNull()
  })

  it('reopening the drawer starts with empty notes', () => {
    list([tire(1, 'FL')])
    render(<TireList vin={VIN} />, { wrapper: withConfirm })
    openAndFill()
    fireEvent.change(dialog().getByLabelText('tireList.notes'), { target: { value: 'left over' } })
    fireEvent.click(dialog().getByText('common:cancel'))
    fireEvent.click(screen.getByText('tireList.addReading'))
    expect(field('reading-notes').value).toBe('')
  })
})
