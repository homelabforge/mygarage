/**
 * A rejected save (G1b-75): a 422 on a field the form shows lands under that
 * field with no banner, and anything else shows the banner. Plus the guard that
 * keeps knownFields in step with what the form registers.
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
})

// Guard for knownFields drift: a 422 on any field this form registers has to
// attach, so it never falls through to the generic banner. No single vehicle
// shows every field, so it walks four that between them do.
// Mutant: drop any name from knownFields and the banner shows.
describe('FuelRecordForm: knownFields covers every registered field', () => {
  const vehicles: Record<string, TestVehicle> = {
    // EV charging fields, kWh and litres, odometer and engine hours.
    pluginHybridDual: mockVehicle({ fuel_type: 'plugin_hybrid', secondary_usage_enabled: true }),
    // DEF level, diesel grade, and the fuel-dispensed picker.
    dieselMultiFuel: mockVehicle({ fuel_type: 'diesel', fuel_type_secondary: 'gasoline' }),
    gasoline: mockVehicle({ fuel_type: 'gasoline' }),
    propane: mockVehicle({ fuel_type: 'propane_lpg' }),
  }

  // Named controls that aren't payload fields go here. None today: the fill-up
  // time, station search and outside temp boxes are controlled and carry no
  // name, so they never reach the sweep.
  const UI_ONLY: string[] = []

  it('guard: a 422 on every registered field attaches, on every vehicle shape', async () => {
    const seen = new Set<string>()
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

      const names = registeredFieldNames(drawerForm(), UI_ONLY)
      names.forEach((n) => seen.add(n))
      mockedApiPost.mockRejectedValueOnce(validationError(Object.fromEntries(names.map((n) => [n, `bad ${n}`]))))
      fireEvent.submit(drawerForm())

      await waitFor(() => expect(mockedApiPost).toHaveBeenCalled())
      // Settled once the catch has run: either the banner or a field message is up.
      await waitFor(() => expect(banner() ?? screen.queryAllByText(/^bad /)[0]).toBeTruthy())
      expect(banner(), `${shape}: ${names.join(', ')}`).toBeNull()
      cleanup()
    }
    // The fields that drifted before have to be in the sweep, or it proves nothing.
    expect([...seen]).toEqual(
      expect.arrayContaining(['soc_start_pct', 'soc_end_pct', 'battery_soh_pct', 'charge_level', 'charge_location'])
    )
  })
})
