/**
 * Clearing a field on edit has to reach the API as null. The update route
 * skips keys that aren't sent (exclude_unset), so an undefined here kept the
 * old value no matter what the form showed. Create is unchanged, and
 * def_fill_level stays out: it isn't seeded, and a null deletes the fill-up's
 * linked DEF record.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, waitFor, fireEvent } from '@testing-library/react'
import { render } from '../../__tests__/test-utils'
import FuelRecordForm from '../FuelRecordForm'
import type { Vehicle } from '../../types/vehicle'
import type { FuelRecord } from '../../types/fuel'

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
  // UnitSession reads the account half too; same answer, nothing to pin here.
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

const VIN = 'TEST12345678901234'

function mockVehicle(overrides: Partial<Vehicle>): void {
  const vehicle = {
    vin: VIN, nickname: 'Test', vehicle_type: 'Car', year: 2024, make: 'Toyota', model: 'Camry',
    created_at: '2024-01-15T00:00:00Z', archived_visible: true, ...overrides,
  }
  mockedApiGet.mockImplementation((url: string) =>
    Promise.resolve({ data: String(url).includes('/fuel') ? { records: [] } : vehicle })
  )
}

const record = (fields: Record<string, unknown>): FuelRecord =>
  ({ id: 42, vin: VIN, date: '2026-03-01', is_full_tank: true, missed_fillup: false, is_hauling: false, ...fields }) as unknown as FuelRecord

const input = (id: string) => document.getElementById(id) as HTMLInputElement

async function clearAndSubmit(ids: string[]): Promise<Record<string, unknown>> {
  for (const id of ids) fireEvent.change(input(id), { target: { value: '' } })
  fireEvent.submit(drawerForm())
  await waitFor(() => expect(mockedApiPut).toHaveBeenCalled())
  return mockedApiPut.mock.calls.at(-1)?.[1] as Record<string, unknown>
}

beforeEach(() => {
  vi.clearAllMocks()
  mockedApiPut.mockResolvedValue({ data: {} })
  localStorage.clear()
  // Open "More details", where the driver, payment, trip, temperature and OBC fields live.
  localStorage.setItem('fuel_form:more_details_expanded', '1')
})

describe('FuelRecordForm: clearing a field on edit', () => {
  it('a gasoline fill-up: every cleared field posts null, and def_fill_level stays out', async () => {
    // Multi-fuel so the fuel-dispensed select shows; dual tracking so engine hours do.
    mockVehicle({ fuel_type: 'gasoline', fuel_type_secondary: 'e85', usage_unit: 'distance', secondary_usage_enabled: true } as Partial<Vehicle>)
    render(
      <FuelRecordForm
        vin={VIN}
        record={record({
          odometer_km: 50000, engine_hours: 120.5, liters: 40, price_per_unit: 1.5, price_basis: 'per_volume',
          rebate: 2, cost: 58, fuel_type_used: 'gasoline', driver_name_freetext: 'Sam',
          payment_method: 'credit', trip_type: 'commute', outside_temp_c: 12, obc_l_per_100km: 8.1,
          obc_avg_speed_kmh: 64, obc_trip_duration_s: 5400, notes: '',
        })}
        onClose={vi.fn()}
        onSuccess={vi.fn()}
      />
    )
    await waitFor(() => expect(input('engine_hours')).toBeInTheDocument())
    await waitFor(() => expect(input('fuel_type_used')).toBeInTheDocument())

    // Quantity and price before rebate and cost, so no auto-calc refills them.
    const body = await clearAndSubmit([
      'odometer_km', 'engine_hours', 'liters', 'price_per_unit', 'rebate', 'cost', 'fuel_type_used',
      'driver_name_freetext', 'payment_method', 'trip_type', 'outside_temp_display',
      'obc_l_per_100km', 'obc_avg_speed_kmh', 'obc_trip_duration_s',
    ])

    for (const key of [
      'odometer_km', 'engine_hours', 'liters', 'price_per_unit', 'rebate', 'cost', 'fuel_type_used',
      'driver_name_freetext', 'payment_method', 'trip_type', 'outside_temp_c',
      'obc_l_per_100km', 'obc_avg_speed_kmh', 'obc_trip_duration_s',
    ]) {
      expect(body[key], key).toBeNull()
    }
    expect(body.def_fill_level).toBeUndefined()
  })

  it('a hybrid charge: the energy, charge-state and charger fields post null', async () => {
    mockVehicle({ fuel_type: 'hybrid' })
    render(
      <FuelRecordForm
        vin={VIN}
        record={record({
          kwh: 30, soc_start_pct: 20, soc_end_pct: 80, battery_soh_pct: 95,
          charge_level: 'L2', charge_location: 'home', liters: 10, price_per_unit: 1.5, price_basis: 'per_volume', cost: 15,
        })}
        onClose={vi.fn()}
        onSuccess={vi.fn()}
      />
    )
    await waitFor(() => expect(input('soc_start_pct')).toBeInTheDocument())

    const body = await clearAndSubmit(['kwh', 'soc_start_pct', 'soc_end_pct', 'battery_soh_pct', 'charge_level', 'charge_location'])

    for (const key of ['kwh', 'soc_start_pct', 'soc_end_pct', 'battery_soh_pct', 'charge_level', 'charge_location']) {
      expect(body[key], key).toBeNull()
    }
  })

  it('a propane fill-up: the propane volume posts null', async () => {
    mockVehicle({ fuel_type: 'propane' })
    render(
      <FuelRecordForm
        vin={VIN}
        record={record({ propane_liters: 30, price_per_unit: 0.9, price_basis: 'per_volume', cost: 27 })}
        onClose={vi.fn()}
        onSuccess={vi.fn()}
      />
    )
    await waitFor(() => expect(input('propane_liters')).toBeInTheDocument())

    const body = await clearAndSubmit(['propane_liters'])

    expect(body.propane_liters).toBeNull()
  })

  it('an untouched edit posts every stored value, hidden and collapsed fields included', async () => {
    // The sweep rests on this: every key that posts null when empty is seeded
    // from the record, so an untouched field can never post null. Hours-only
    // hides the odometer, single-fuel hides the fuel-dispensed select,
    // gasoline hides the energy and propane fields, and More details stays
    // COLLAPSED here, so none of those inputs is mounted.
    localStorage.removeItem('fuel_form:more_details_expanded')
    mockVehicle({ fuel_type: 'gasoline', usage_unit: 'hours', secondary_usage_enabled: false } as Partial<Vehicle>)
    const stored = {
      odometer_km: 50000, engine_hours: 120.5, liters: 40, propane_liters: 5, kwh: 3,
      soc_start_pct: 20, soc_end_pct: 80, battery_soh_pct: 95, charge_level: 'L2', charge_location: 'home',
      price_per_unit: 1.5, cost: 60, rebate: 2, fuel_type_used: 'gasoline', driver_name_freetext: 'Sam',
      payment_method: 'cash', trip_type: 'commute', outside_temp_c: 12, obc_l_per_100km: 8.1,
      obc_avg_speed_kmh: 64,
    }
    render(
      <FuelRecordForm
        vin={VIN}
        record={record({ ...stored, price_basis: 'per_volume', obc_trip_duration_s: 5400 })}
        onClose={vi.fn()}
        onSuccess={vi.fn()}
      />
    )
    await waitFor(() => expect(input('engine_hours')).toBeInTheDocument())
    expect(input('odometer_km')).toBeNull()
    expect(input('payment_method')).toBeNull()

    const body = await clearAndSubmit([])

    expect(body).toMatchObject(stored)
    // Seeded as text, so the raw string goes back for the server to parse.
    expect(body.obc_trip_duration_s).toBe('5400')
    expect(body.def_fill_level).toBeUndefined()
  })
})
