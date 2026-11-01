/**
 * Octane + diesel grade (#164): fuel-type-gated visibility, create-mode
 * prefill from the vehicle's last fill-up, and the null-on-update payload
 * convention (issue #108 shape).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, waitFor, fireEvent } from '@testing-library/react'
import { render } from '../../__tests__/test-utils'
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

function mockVehicle(overrides: Partial<Vehicle> = {}): Vehicle {
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
  } as Vehicle
}

/** Route the two GETs the form makes: the vehicle and the last-fillup list. */
function mockGets(vehicle: Vehicle, lastRecords: Record<string, unknown>[] = []): void {
  mockedApiGet.mockImplementation((url: string) => {
    if (String(url).includes('/fuel')) {
      return Promise.resolve({ data: { records: lastRecords } })
    }
    return Promise.resolve({ data: vehicle })
  })
}

const DEFAULT_PROPS = {
  vin: 'TEST12345678901234',
  onClose: vi.fn(),
  onSuccess: vi.fn(),
}

const octaneInput = (): HTMLInputElement | null =>
  document.getElementById('octane') as HTMLInputElement | null
const gradeSelect = (): HTMLSelectElement | null =>
  document.getElementById('diesel_grade') as HTMLSelectElement | null

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
})

describe('FuelRecordForm — octane/diesel-grade visibility', () => {
  it('a gasoline vehicle shows the octane input and no diesel grade', async () => {
    mockGets(mockVehicle({ fuel_type: 'gasoline' }))
    render(<FuelRecordForm {...DEFAULT_PROPS} />)
    await waitFor(() => expect(octaneInput()).toBeInTheDocument())
    expect(gradeSelect()).not.toBeInTheDocument()
  })

  it('a diesel vehicle shows the diesel grade select and no octane', async () => {
    mockGets(mockVehicle({ fuel_type: 'diesel' }))
    render(<FuelRecordForm {...DEFAULT_PROPS} />)
    await waitFor(() => expect(gradeSelect()).toBeInTheDocument())
    expect(octaneInput()).not.toBeInTheDocument()
  })

  it('an electric vehicle shows neither', async () => {
    mockGets(mockVehicle({ fuel_type: 'electric' }))
    render(<FuelRecordForm {...DEFAULT_PROPS} />)
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())
    expect(octaneInput()).not.toBeInTheDocument()
    expect(gradeSelect()).not.toBeInTheDocument()
  })

  it('E85 (flex fuel dispensed) also rates an octane input', async () => {
    // Multi-fuel vehicle whose fill was E85: the gate follows the fuel
    // DISPENSED (watch), not just the vehicle's primary type.
    mockGets(mockVehicle({ fuel_type: 'diesel' }))
    render(
      <FuelRecordForm
        {...DEFAULT_PROPS}
        record={{ id: 5, vin: DEFAULT_PROPS.vin, date: '2026-05-01', fuel_type_used: 'e85' } as never}
      />,
    )
    await waitFor(() => expect(octaneInput()).toBeInTheDocument())
    expect(gradeSelect()).not.toBeInTheDocument()
  })
})

describe('FuelRecordForm — create-mode prefill from the last fill-up', () => {
  it('seeds octane from the newest record', async () => {
    mockGets(mockVehicle({ fuel_type: 'gasoline' }), [
      { id: 9, octane: 93, diesel_grade: null },
      { id: 8, octane: 87, diesel_grade: null },
    ])
    render(<FuelRecordForm {...DEFAULT_PROPS} />)
    await waitFor(() => expect(octaneInput()?.value).toBe('93'))
  })

  it('seeds the diesel grade for a diesel vehicle', async () => {
    mockGets(mockVehicle({ fuel_type: 'diesel' }), [{ id: 9, octane: null, diesel_grade: 'offroad' }])
    render(<FuelRecordForm {...DEFAULT_PROPS} />)
    await waitFor(() => expect(gradeSelect()?.value).toBe('offroad'))
  })

  it('does not prefill in edit mode', async () => {
    mockGets(mockVehicle({ fuel_type: 'gasoline' }), [{ id: 9, octane: 93 }])
    render(
      <FuelRecordForm
        {...DEFAULT_PROPS}
        record={{ id: 5, vin: DEFAULT_PROPS.vin, date: '2026-05-01' } as never}
      />,
    )
    await waitFor(() => expect(octaneInput()).toBeInTheDocument())
    expect(octaneInput()?.value).toBe('')
  })
})

describe('FuelRecordForm — submit payload', () => {
  it('an edited octane goes out as an int and a cleared one as null (issue-#108 convention)', async () => {
    mockGets(mockVehicle({ fuel_type: 'gasoline' }))
    render(
      <FuelRecordForm
        {...DEFAULT_PROPS}
        record={{ id: 5, vin: DEFAULT_PROPS.vin, date: '2026-05-01', octane: 87 } as never}
      />,
    )
    await waitFor(() => expect(octaneInput()).toBeInTheDocument())
    expect(octaneInput()?.value).toBe('87')

    fireEvent.change(octaneInput()!, { target: { value: '91' } })
    fireEvent.submit(drawerForm())
    await waitFor(() => expect(mockedApiPut).toHaveBeenCalled())
    let body = mockedApiPut.mock.calls.at(-1)?.[1] as Record<string, unknown>
    expect(body.octane).toBe(91)

    fireEvent.change(octaneInput()!, { target: { value: '' } })
    fireEvent.submit(drawerForm())
    await waitFor(() => expect(mockedApiPut).toHaveBeenCalledTimes(2))
    body = mockedApiPut.mock.calls.at(-1)?.[1] as Record<string, unknown>
    expect(body.octane).toBeNull()
  })

  it('a chosen diesel grade goes out on the wire', async () => {
    mockGets(mockVehicle({ fuel_type: 'diesel' }))
    render(
      <FuelRecordForm
        {...DEFAULT_PROPS}
        record={{ id: 6, vin: DEFAULT_PROPS.vin, date: '2026-05-01' } as never}
      />,
    )
    await waitFor(() => expect(gradeSelect()).toBeInTheDocument())
    fireEvent.change(gradeSelect()!, { target: { value: 'offroad' } })
    fireEvent.submit(drawerForm())
    await waitFor(() => expect(mockedApiPut).toHaveBeenCalled())
    const body = mockedApiPut.mock.calls.at(-1)?.[1] as Record<string, unknown>
    expect(body.diesel_grade).toBe('offroad')
  })

  it('an out-of-band octane blocks submission with the validation message', async () => {
    mockGets(mockVehicle({ fuel_type: 'gasoline' }))
    render(
      <FuelRecordForm
        {...DEFAULT_PROPS}
        record={{ id: 7, vin: DEFAULT_PROPS.vin, date: '2026-05-01' } as never}
      />,
    )
    await waitFor(() => expect(octaneInput()).toBeInTheDocument())
    fireEvent.change(octaneInput()!, { target: { value: '893' } })
    fireEvent.submit(drawerForm())
    await screen.findByText('common:validation.fuel.octaneTooLarge')
    expect(mockedApiPut).not.toHaveBeenCalled()
  })
})

describe('FuelRecordForm — codex code-review fixes', () => {
  it('an invalid octane hidden by switching to diesel cannot block the save (R1-M3)', async () => {
    // Multi-fuel vehicle so the fuel_type_used select renders.
    mockGets(mockVehicle({ fuel_type: 'gasoline', fuel_type_secondary: 'diesel' } as never))
    render(
      <FuelRecordForm
        {...DEFAULT_PROPS}
        record={{ id: 8, vin: DEFAULT_PROPS.vin, date: '2026-05-01', fuel_type_used: 'gasoline' } as never}
      />,
    )
    await waitFor(() => expect(octaneInput()).toBeInTheDocument())
    fireEvent.change(octaneInput()!, { target: { value: '893' } })

    const fuelTypeSelect = document.getElementById('fuel_type_used') as HTMLSelectElement
    fireEvent.change(fuelTypeSelect, { target: { value: 'diesel' } })
    await waitFor(() => expect(octaneInput()).not.toBeInTheDocument())

    fireEvent.submit(drawerForm())
    await waitFor(() => expect(mockedApiPut).toHaveBeenCalled())
    const body = mockedApiPut.mock.calls.at(-1)?.[1] as Record<string, unknown>
    expect(body.octane).toBeNull()
    expect(body.fuel_type_used).toBe('diesel')
  })

  it('a value typed and cleared before the history resolves stays cleared (R1-M4)', async () => {
    let resolveHistory: (v: unknown) => void = () => {}
    mockedApiGet.mockImplementation((url: string) => {
      if (String(url).includes('/fuel')) {
        return new Promise((resolve) => {
          resolveHistory = resolve
        })
      }
      return Promise.resolve({ data: mockVehicle({ fuel_type: 'gasoline' }) })
    })
    render(<FuelRecordForm {...DEFAULT_PROPS} />)
    await waitFor(() => expect(octaneInput()).toBeInTheDocument())

    fireEvent.change(octaneInput()!, { target: { value: '91' } })
    fireEvent.change(octaneInput()!, { target: { value: '' } })

    resolveHistory({ data: { records: [{ id: 9, octane: 93 }] } })
    // Give the resolved promise's then() a tick to (not) write.
    await new Promise((r) => setTimeout(r, 0))
    expect(octaneInput()?.value).toBe('')
  })
})
