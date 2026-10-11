/**
 * #217 on the tire dialogs: an hours-only vehicle is asked for the hour meter
 * and never the odometer, a dual vehicle for both, and a cleared date blocks
 * every Save (G4-52) instead of posting '' for a 422.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'

const useTiresMock = vi.fn()
const writeMock = vi.fn()
const useAddTireReadingMock = vi.fn()
const useTireSetsMock = vi.fn()

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
vi.mock('../../hooks/useUnitPreference', () => ({
  useUnitPreference: () => ({
    system: 'imperial',
    showBoth: false,
    gallonStandard: 'us',
    units: {
      distance: 'mi', speed: 'mph', length: 'ft', volume: 'gal_us', consumption: 'mpg_us',
      pressure: 'psi', temperature: 'f', mass: 'lb', torque: 'lbft', tread: 'in32', secondary_gallon: 'us',
    },
  }),
}))

import TireList from '../TireList'

const VIN = '1HGCM82633A004352'
const HOURS = { usage_axis: 'hours', tracks_distance: false, tracks_hours: true }
const DUAL = { usage_axis: 'distance', tracks_distance: true, tracks_hours: true }

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
const FULL = [tire(1, 'FL'), tire(2, 'FR'), tire(3, 'RL'), tire(4, 'RR'), tire(5, null)]

const list = (tires: unknown[], flags: Record<string, unknown> = {}) =>
  useTiresMock.mockReturnValue({ data: { tires, total: tires.length, ...flags }, isLoading: false, error: null })
const dialog = () => within(screen.getByRole('dialog'))
const field = (id: string) => document.getElementById(id) as HTMLInputElement

describe('TireList on the hour meter (#217)', () => {
  const mutate = vi.fn()
  const addReading = vi.fn()
  beforeEach(() => {
    mutate.mockReset()
    addReading.mockReset()
    toastError.mockReset()
    writeMock.mockReturnValue({ mutate, isPending: false })
    useAddTireReadingMock.mockReturnValue({ mutate: addReading, isPending: false })
    useTireSetsMock.mockReturnValue({ data: { sets: [], total: 0 }, isLoading: false, error: null })
  })

  it('Add Tire on an hours-only vehicle asks for the hour meter and sends it', () => {
    list([], HOURS)
    render(<TireList vin={VIN} />)
    fireEvent.click(screen.getByText('tireList.add'))
    expect(screen.queryByLabelText('tireList.odometerWithUnit')).toBeNull()
    fireEvent.change(field('tire-mount-hours'), { target: { value: '120.5' } })
    fireEvent.click(dialog().getByText('common:save'))
    const payload = mutate.mock.calls[0][0]
    expect(payload.mounted_hours).toBe(120.5)
    expect(payload).not.toHaveProperty('mounted_odometer_km')
  })

  it('sends a typed 0', () => {
    list([], HOURS)
    render(<TireList vin={VIN} />)
    fireEvent.click(screen.getByText('tireList.add'))
    fireEvent.change(field('tire-mount-hours'), { target: { value: '0' } })
    fireEvent.click(dialog().getByText('common:save'))
    expect(mutate.mock.calls[0][0].mounted_hours).toBe(0)
  })

  it('Log reading on an hours-only vehicle takes the hour meter, not the odometer', () => {
    list([tire(1, 'FL')], HOURS)
    render(<TireList vin={VIN} />)
    fireEvent.click(screen.getByText('tireList.addReading'))
    expect(field('reading-odo')).toBeNull()
    fireEvent.change(field('reading-hours'), { target: { value: '150' } })
    fireEvent.click(dialog().getByText('common:save'))
    const payload = addReading.mock.calls[0][0]
    expect(payload.engine_hours).toBe(150)
    expect(payload).not.toHaveProperty('odometer_km')
  })

  it('a dual vehicle sends both readings', () => {
    list([], DUAL)
    render(<TireList vin={VIN} />)
    fireEvent.click(screen.getByText('tireList.add'))
    fireEvent.change(field('tire-mount-odometer'), { target: { value: '1000' } })
    fireEvent.change(field('tire-mount-hours'), { target: { value: '50' } })
    fireEvent.click(dialog().getByText('common:save'))
    const payload = mutate.mock.calls[0][0]
    expect(payload.mounted_odometer_km).toBeCloseTo(1609.344)
    expect(payload.mounted_hours).toBe(50)
  })

  it('a distance-only vehicle sends no hours key at all', () => {
    list([])
    render(<TireList vin={VIN} />)
    fireEvent.click(screen.getByText('tireList.add'))
    expect(field('tire-mount-hours')).toBeNull()
    fireEvent.click(dialog().getByText('common:save'))
    expect(mutate.mock.calls[0][0]).not.toHaveProperty('mounted_hours')
  })
})

describe('A cleared date blocks Save (G4-52)', () => {
  const mutate = vi.fn()
  const addReading = vi.fn()
  beforeEach(() => {
    mutate.mockReset()
    addReading.mockReset()
    toastError.mockReset()
    writeMock.mockReturnValue({ mutate, isPending: false })
    useAddTireReadingMock.mockReturnValue({ mutate: addReading, isPending: false })
    useTireSetsMock.mockReturnValue({
      data: { sets: [{ id: 7, vin: VIN, name: 'Winter', notes: null, created_at: '2026-01-01T00:00:00', tire_ids: [5], mounted_count: 0 }], total: 1 },
      isLoading: false,
      error: null,
    })
    list(FULL)
  })

  const refused = (): void => {
    expect(toastError).toHaveBeenCalledWith('tireList.eventDateRequired')
    expect(mutate).not.toHaveBeenCalled()
    expect(addReading).not.toHaveBeenCalled()
  }

  it('in Add Tire', () => {
    render(<TireList vin={VIN} />)
    fireEvent.click(screen.getByText('tireList.add'))
    fireEvent.change(field('tire-mount-date'), { target: { value: '' } })
    fireEvent.click(dialog().getByText('common:save'))
    refused()
  })

  it('in Mount', () => {
    render(<TireList vin={VIN} />)
    fireEvent.click(screen.getByText('tireList.mount'))
    fireEvent.change(field('mount-date'), { target: { value: '' } })
    fireEvent.click(dialog().getByText('tireList.mount'))
    refused()
  })

  it('in Dismount', () => {
    render(<TireList vin={VIN} />)
    fireEvent.click(screen.getAllByText('tireList.dismount')[0])
    fireEvent.change(field('dismount-date'), { target: { value: '' } })
    fireEvent.click(dialog().getByText('tireList.dismount'))
    refused()
  })

  it('in Retire', () => {
    render(<TireList vin={VIN} />)
    fireEvent.click(screen.getAllByText('tireList.retire')[0])
    fireEvent.change(field('retire-date'), { target: { value: '' } })
    fireEvent.click(dialog().getByText('tireList.retire'))
    refused()
  })

  it('in Rotate', () => {
    render(<TireList vin={VIN} />)
    fireEvent.click(screen.getByText('tireList.rotate'))
    fireEvent.change(field('rotate-date'), { target: { value: '' } })
    fireEvent.click(dialog().getByText('tireList.rotate'))
    refused()
  })

  it('in Set fit', () => {
    render(<TireList vin={VIN} />)
    fireEvent.click(screen.getByText('tireList.sets'))
    fireEvent.click(dialog().getByText('tireList.setFit'))
    fireEvent.change(field('set-fit-7-date'), { target: { value: '' } })
    const fits = dialog().getAllByText('tireList.setFit')
    fireEvent.click(fits[fits.length - 1])
    refused()
  })

  it('in Log reading', () => {
    render(<TireList vin={VIN} />)
    fireEvent.click(screen.getAllByText('tireList.addReading')[0])
    fireEvent.change(field('reading-date'), { target: { value: '' } })
    fireEvent.click(dialog().getByText('common:save'))
    refused()
  })
})
