/**
 * A rejected save (G1b-75): a 422 on a field the form shows lands under that
 * field with no banner, and anything else shows the banner. Plus the guard that
 * every field a 422 can name shows it somewhere.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, waitFor, fireEvent, cleanup } from '@testing-library/react'
import { render } from '../../__tests__/test-utils'
import { registeredFieldNames, validationError } from '../../__tests__/serverErrors'
import FuelRecordForm from '../FuelRecordForm'
import type { Vehicle } from '../../types/vehicle'

const drawerForm = (): HTMLFormElement =>
  screen.getByRole('dialog').querySelector('form') as HTMLFormElement

const mockedApiGet = vi.fn()
const mockedApiPost = vi.fn().mockResolvedValue({ data: {} })
const mockedApiPut = vi.fn().mockResolvedValue({ data: {} })

vi.mock('../../services/api', () => ({
  default: {
    get: (...args: unknown[]) => mockedApiGet(...args),
    post: (...args: unknown[]) => mockedApiPost(...args),
    put: (...args: unknown[]) => mockedApiPut(...args),
  },
}))

vi.mock('../../hooks/useUnitPreference', async () => {
  const { METRIC_UNITS } = await import('@/__tests__/factories')
  const unitPreference = () => ({ system: 'metric', showBoth: false, units: METRIC_UNITS })
  return {
    useUnitPreference: unitPreference,
    useAccountUnitPreference: unitPreference,
  }
})

vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({ user: null }),
}))

vi.mock('../../hooks/useTimeFormat', () => ({
  useTimeFormat: () => ({ timeFormat: '24h' }),
}))

type TestVehicle = Vehicle & { fuel_type_secondary?: string | null }

function mockVehicle(overrides: Partial<TestVehicle> = {}): TestVehicle {
  return {
    vin: 'TEST12345678901234',
    nickname: 'Test Car',
    vehicle_type: 'Car',
    year: 2024,
    make: 'Toyota',
    model: 'Camry',
    created_at: '2024-01-15T00:00:00Z',
    archived_visible: true,
    fuel_type: 'gasoline',
    ...overrides,
  } as TestVehicle
}

/** The vehicle GET drives which fields show; the last-fillup list stays empty. */
function mockGets(vehicle: TestVehicle): void {
  mockedApiGet.mockImplementation((url: string) => {
    if (String(url).includes('/fuel')) return Promise.resolve({ data: { records: [] } })
    return Promise.resolve({ data: vehicle })
  })
}

const DEFAULT_PROPS = {
  vin: 'TEST12345678901234',
  onClose: vi.fn(),
  onSuccess: vi.fn(),
}

const control = (id: string): HTMLInputElement | null => document.getElementById(id) as HTMLInputElement | null
const banner = (): HTMLElement | null => screen.queryByText(/^Failed to fuel\.saveAction\./)

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
})

describe('FuelRecordForm: a rejected save', () => {
  it('a non-422 failure shows the banner and no field error', async () => {
    mockGets(mockVehicle())
    mockedApiPost.mockRejectedValueOnce(new Error('Network Error'))
    render(<FuelRecordForm {...DEFAULT_PROPS} />)
    await waitFor(() => expect(control('octane')).not.toBeNull())
    fireEvent.change(control('cost')!, { target: { value: '42.00' } })
    fireEvent.submit(drawerForm())

    expect(await screen.findByText('Failed to fuel.saveAction. Network Error')).toBeInTheDocument()
    expect(control('cost-error')).toBeNull()
  })

  it('a 422 on cost shows under cost and no banner', async () => {
    mockGets(mockVehicle())
    mockedApiPost.mockRejectedValueOnce(validationError({ cost: 'Input should be a valid decimal' }))
    render(<FuelRecordForm {...DEFAULT_PROPS} />)
    await waitFor(() => expect(control('octane')).not.toBeNull())
    fireEvent.change(control('cost')!, { target: { value: '42.00' } })
    fireEvent.submit(drawerForm())

    await waitFor(() => expect(control('cost-error')).not.toBeNull())
    expect(control('cost-error')).toHaveTextContent('Input should be a valid decimal')
    expect(banner()).toBeNull()
  })

  it('a 422 on an EV charging field shows under it and no banner', async () => {
    mockGets(mockVehicle({ fuel_type: 'electric' }))
    mockedApiPost.mockRejectedValueOnce(validationError({ soc_start_pct: 'Input should be less than or equal to 100' }))
    render(<FuelRecordForm {...DEFAULT_PROPS} />)
    await waitFor(() => expect(control('soc_start_pct')).not.toBeNull())
    fireEvent.change(control('soc_start_pct')!, { target: { value: '20' } })
    fireEvent.submit(drawerForm())

    await waitFor(() => expect(mockedApiPost).toHaveBeenCalled())
    await waitFor(() => expect(control('soc_start_pct-error')).not.toBeNull())
    expect(control('soc_start_pct-error')).toHaveTextContent('Input should be less than or equal to 100')
    expect(banner()).toBeNull()
  })

  it('a 422 on the driver shows under the driver field and no banner', async () => {
    localStorage.setItem('fuel_form:more_details_expanded', '1')
    mockGets(mockVehicle())
    mockedApiPost.mockRejectedValueOnce(validationError({ driver_name_freetext: 'String should have at most 100 characters' }))
    render(<FuelRecordForm {...DEFAULT_PROPS} />)
    await waitFor(() => expect(control('driver_name_freetext')).not.toBeNull())
    fireEvent.submit(drawerForm())

    await waitFor(() => expect(mockedApiPost).toHaveBeenCalled())
    await waitFor(() => expect(control('driver_name_freetext-error')).not.toBeNull())
    expect(control('driver_name_freetext-error')).toHaveTextContent('String should have at most 100 characters')
    expect(banner()).toBeNull()
  })

  it('a 422 on a checkbox shows the banner, since a checkbox has nowhere to show it', async () => {
    mockGets(mockVehicle())
    mockedApiPost.mockRejectedValueOnce(validationError({ is_full_tank: 'Input should be a valid boolean' }))
    render(<FuelRecordForm {...DEFAULT_PROPS} />)
    await waitFor(() => expect(control('is_full_tank')).not.toBeNull())
    fireEvent.submit(drawerForm())

    await waitFor(() => expect(banner()).not.toBeNull())
  })
})

// Guard for knownFields drift and for silent fields: a 422 on any field this
// form registers has to show up, under the field or, for the few with nowhere
// to show it, in the banner. One 422 per name, so a stray banner can't hide a
// field that stayed silent. No single vehicle shows every field, so it walks
// four that between them do.
// Mutants: drop a name from knownFields (it banners), or drop a Field's error
// prop (it goes silent).
describe('FuelRecordForm: every field a 422 can name shows it', () => {
  const vehicles: Record<string, TestVehicle> = {
    // EV charging fields, kWh and litres, odometer and engine hours.
    pluginHybridDual: mockVehicle({ fuel_type: 'plugin_hybrid', secondary_usage_enabled: true }),
    // DEF level, diesel grade, and the fuel-dispensed picker.
    dieselMultiFuel: mockVehicle({ fuel_type: 'diesel', fuel_type_secondary: 'gasoline' }),
    gasoline: mockVehicle({ fuel_type: 'gasoline' }),
    propane: mockVehicle({ fuel_type: 'propane_lpg' }),
  }

  // Named controls that aren't payload fields go here. None today: the fill-up
  // time and station search boxes are controlled and carry no name.
  const UI_ONLY: string[] = []
  // Checkboxes have no inline error, so they stay out of knownFields and a 422
  // on one goes to the banner.
  const BANNER_ROUTED = ['is_full_tank', 'missed_fillup', 'is_hauling', 'one_time_visit']
  // In knownFields but nameless: the outside temp box is controlled, and its
  // error shows under that box.
  const CONTROLLED = ['outside_temp_c']

  type Outcome = 'field' | 'banner' | 'silent'
  /** Where a 422 on `name` ended up. Each message is unique, so an older one can't answer. */
  const rejectOne = async (name: string, msg: string): Promise<Outcome> => {
    const calls = mockedApiPost.mock.calls.length
    mockedApiPost.mockRejectedValueOnce(validationError({ [name]: msg }))
    fireEvent.submit(drawerForm())
    await waitFor(() => expect(mockedApiPost).toHaveBeenCalledTimes(calls + 1))
    try {
      await waitFor(() => expect(screen.queryByText(msg) ?? banner()).toBeTruthy(), { timeout: 300 })
    } catch {
      return 'silent'
    }
    return screen.queryByText(msg) ? 'field' : 'banner'
  }

  it('guard: a 422 on each field shows under it, or in the banner for a checkbox', async () => {
    const checked = new Set<string>()
    const wrong: string[] = []
    for (const [shape, vehicle] of Object.entries(vehicles)) {
      vi.clearAllMocks()
      // Open "More details" so the station, driver, payment and OBC fields render.
      localStorage.setItem('fuel_form:more_details_expanded', '1')
      mockGets(vehicle)
      render(<FuelRecordForm {...DEFAULT_PROPS} />)
      await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())
      await waitFor(() => expect(control('obc_trip_duration_s')).not.toBeNull())
      // Let the vehicle-driven fields settle before reading the names.
      if (shape === 'pluginHybridDual') await waitFor(() => expect(control('soc_start_pct')).not.toBeNull())
      if (shape === 'dieselMultiFuel') await waitFor(() => expect(control('diesel_grade')).not.toBeNull())
      if (shape === 'gasoline') await waitFor(() => expect(control('octane')).not.toBeNull())
      if (shape === 'propane') await waitFor(() => expect(control('propane_liters')).not.toBeNull())

      const names = [...registeredFieldNames(drawerForm(), UI_ONLY), ...CONTROLLED].filter((n) => !checked.has(n))
      for (const [i, name] of names.entries()) {
        checked.add(name)
        const want: Outcome = BANNER_ROUTED.includes(name) ? 'banner' : 'field'
        const got = await rejectOne(name, `bad ${name} ${shape} ${i}`)
        if (got !== want) wrong.push(`${name}: ${got}`)
      }
      cleanup()
    }
    expect(wrong).toEqual([])
    // The fields that drifted or went silent before have to be in the sweep, or it proves nothing.
    expect([...checked]).toEqual(
      expect.arrayContaining([
        'soc_start_pct', 'soc_end_pct', 'battery_soh_pct', 'charge_level', 'charge_location',
        'driver_name_freetext', 'obc_trip_duration_s', ...BANNER_ROUTED, ...CONTROLLED,
      ])
    )
  })
})
