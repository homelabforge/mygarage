/**
 * #217 on the tire dialogs: an hours-only vehicle is asked for the hour meter
 * and never the odometer, a dual vehicle for both, and a cleared date blocks
 * every Save (G4-52) instead of posting '' for a 422. The card shows an
 * hours tire's figures in hours.
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

describe('Every tire move sends the hour meter on an hours-only vehicle (#217)', () => {
  const mutate = vi.fn()
  beforeEach(() => {
    mutate.mockReset()
    writeMock.mockReturnValue({ mutate, isPending: false })
    useAddTireReadingMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useTireSetsMock.mockReturnValue({
      data: { sets: [{ id: 7, vin: VIN, name: 'Winter', notes: null, created_at: '2026-01-01T00:00:00', tire_ids: [5], mounted_count: 0 }], total: 1 },
      isLoading: false,
      error: null,
    })
    list(FULL, HOURS)
  })

  // Each dialog opened and saved the way the G4-52 cases drive it.
  const openSet = (): void => {
    fireEvent.click(screen.getByText('tireList.sets'))
    fireEvent.click(dialog().getByText('tireList.setFit'))
  }
  const saveSet = (): void => {
    const fits = dialog().getAllByText('tireList.setFit')
    fireEvent.click(fits[fits.length - 1])
  }
  it.each([
    {
      name: 'Mount', hoursKey: 'mounted_hours', odometerKey: 'mounted_odometer_km', id: 'mount-hours',
      open: () => fireEvent.click(screen.getByText('tireList.mount')),
      save: () => fireEvent.click(dialog().getByText('tireList.mount')),
    },
    {
      name: 'Dismount', hoursKey: 'dismounted_hours', odometerKey: 'dismounted_odometer_km', id: 'dismount-hours',
      open: () => fireEvent.click(screen.getAllByText('tireList.dismount')[0]),
      save: () => fireEvent.click(dialog().getByText('tireList.dismount')),
    },
    {
      name: 'Retire', hoursKey: 'dismounted_hours', odometerKey: 'dismounted_odometer_km', id: 'retire-hours',
      open: () => fireEvent.click(screen.getAllByText('tireList.retire')[0]),
      save: () => fireEvent.click(dialog().getByText('tireList.retire')),
    },
    {
      name: 'Rotate', hoursKey: 'engine_hours', odometerKey: 'odometer_km', id: 'rotate-hours',
      open: () => fireEvent.click(screen.getByText('tireList.rotate')),
      save: () => fireEvent.click(dialog().getByText('tireList.rotate')),
    },
    {
      name: 'Set fit', hoursKey: 'engine_hours', odometerKey: 'odometer_km', id: 'set-fit-7-hours',
      open: openSet,
      save: saveSet,
    },
  ])('$name sends $hoursKey and no odometer', ({ hoursKey, odometerKey, id, open, save }) => {
    render(<TireList vin={VIN} />)
    open()
    fireEvent.change(field(id), { target: { value: '212.3' } })
    save()
    expect(mutate).toHaveBeenCalledTimes(1)
    const payload = mutate.mock.calls[0][0]
    expect(payload[hoursKey]).toBe(212.3)
    expect(payload).not.toHaveProperty(odometerKey)
  })
})

describe('The card on the hour meter (#217)', () => {
  beforeEach(() => {
    writeMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useAddTireReadingMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useTireSetsMock.mockReturnValue({ data: { sets: [], total: 0 }, isLoading: false, error: null })
  })

  const hoursTire = (overrides: Record<string, unknown> = {}) => ({
    ...tire(1, 'FL'),
    usage_axis: 'hours',
    wear_status: 'projected',
    projected_usage_remaining: '250.0',
    projected_km_remaining: null,
    projected_wear_date: '2026-03-02',
    distance_status: 'complete',
    usage_on_tire: '60.0',
    distance_km: null,
    ...overrides,
  })

  it('shows hours on the tire and the projection in hours', () => {
    list([hoursTire()], HOURS)
    render(<TireList vin={VIN} />)
    expect(screen.getByText('tireList.hoursOnTire')).toBeInTheDocument()
    expect(screen.queryByText('tireList.distanceOnTire')).toBeNull()
    expect(screen.getByText('60.0 hr')).toBeInTheDocument()
    expect(screen.getByText(/^~250\.0 hr/)).toBeInTheDocument()
  })

  it('asks for the hour meter when the readings lack it', () => {
    list([hoursTire({ wear_status: 'no_reading_odometers', projected_usage_remaining: null })], HOURS)
    render(<TireList vin={VIN} />)
    expect(screen.getByText('tireList.wear.needsReadingHours')).toBeInTheDocument()
    expect(screen.queryByText('tireList.wear.needsReadingOdometer')).toBeNull()
  })

  it('asks for the hour meter on the mount when nothing is bounded', () => {
    list([hoursTire({ distance_status: 'nothing_bounded', usage_on_tire: null })], HOURS)
    render(<TireList vin={VIN} />)
    expect(screen.getByText('tireList.distance.nothingBoundedHours')).toBeInTheDocument()
  })

  it('says hours, not odometer, when the mount date is known and its hours are not', () => {
    list([hoursTire()], HOURS)
    render(<TireList vin={VIN} />)
    expect(screen.getByText('tireList.mountedDateOnlyHours')).toBeInTheDocument()
    expect(screen.queryByText('tireList.mountedDateOnly')).toBeNull()
  })

  it('bounds the mount line by the period hours', () => {
    const t1 = hoursTire()
    list([{ ...t1, mount_periods: [{ ...t1.mount_periods[0], mounted_hours: '120.0' }] }], HOURS)
    render(<TireList vin={VIN} />)
    expect(screen.getByText('tireList.mountedLine')).toBeInTheDocument()
    expect(screen.queryByText('tireList.mountedDateOnlyHours')).toBeNull()
  })

  it('reads the known hours on a partial history', () => {
    list([hoursTire({ distance_status: 'incomplete', usage_on_tire: null, known_usage: '40.0', known_usage_since: '2026-02-01' })], HOURS)
    render(<TireList vin={VIN} />)
    expect(screen.getByText('tireList.distance.since')).toBeInTheDocument()
    expect(screen.queryByText('tireList.distance.nothingBoundedHours')).toBeNull()
  })
})

describe('Editing a reading follows the axes the vehicle takes (#225)', () => {
  const updateReading = vi.fn()
  const READING = {
    id: 31, tire_id: 1, vin: VIN, position: 'FL', recorded_at: '2026-06-10', odometer_km: '170.00',
    engine_hours: '150.0', tread_depth_mm: '7.00', pressure_kpa: null, notes: null, created_at: '2026-06-10T00:00:00',
  }
  beforeEach(() => {
    updateReading.mockReset()
    useUpdateTireReadingMock.mockReturnValue({ mutate: updateReading, isPending: false })
    writeMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useAddTireReadingMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useTireSetsMock.mockReturnValue({ data: { sets: [], total: 0 }, isLoading: false, error: null })
  })
  const openEditor = (): void => {
    render(<TireList vin={VIN} />)
    fireEvent.click(screen.getByRole('button', { name: 'tireList.historyOpen' }))
    fireEvent.click(screen.getByRole('button', { name: 'tireList.readingEditLabel' }))
  }
  const editor = () => within(screen.getByRole('dialog', { name: 'tireList.editReadingTitle' }))

  it('on an hours-only vehicle edits the hour meter and leaves the junk odometer out', () => {
    list([{ ...tire(1, 'FL'), readings: [READING] }], HOURS)
    openEditor()
    expect(field('reading-edit-odometer')).toBeNull()
    fireEvent.change(field('reading-edit-hours'), { target: { value: '155' } })
    fireEvent.click(editor().getByText('common:save'))
    const payload = updateReading.mock.calls[0][0]
    expect(payload).toMatchObject({ tireId: 1, readingId: 31, engine_hours: 155 })
    expect(payload).not.toHaveProperty('odometer_km')
  })

  it('on a dual vehicle edits both', () => {
    list([{ ...tire(1, 'FL'), readings: [READING] }], DUAL)
    openEditor()
    fireEvent.click(editor().getByText('common:save'))
    expect(updateReading.mock.calls[0][0]).toMatchObject({ odometer_km: 170, engine_hours: 150 })
  })
})
