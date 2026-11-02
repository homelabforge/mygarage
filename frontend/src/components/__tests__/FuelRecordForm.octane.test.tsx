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

// #211 — the country profile the form consults for pump names, the octane
// scale and the diesel distinction. Null (the default) is "no national rule",
// which keeps every test above this block on the pre-#211 behaviour.
const profileState = vi.hoisted(() => ({ country: null as string | null, profile: null as unknown }))

vi.mock('../../hooks/useResolvedCountry', () => ({
  useResolvedCountry: () => profileState.country,
}))

vi.mock('../../hooks/queries/useCountryProfile', () => ({
  useCountryProfile: (country: string | null) => ({
    data: country ? profileState.profile : undefined,
    isLoading: false,
  }),
}))

const FR_PROFILE = {
  country: 'FR',
  extends: 'EU',
  names: {},
  currency: 'EUR',
  inspection: null,
  fuel: {
    octane_scale: 'RON',
    diesel_dyed_distinction: false,
    grades: [
      { id: 'sp95_e10', label: 'SP95-E10', grade: 'E10', octane: 95, fuel_type: 'gasoline' },
      { id: 'sp95', label: 'SP95', grade: 'E5', octane: 95, fuel_type: 'gasoline' },
      { id: 'sp98', label: 'SP98', grade: 'E5', octane: 98, fuel_type: 'gasoline' },
      { id: 'gazole', label: 'Gazole (B7)', grade: 'B7', octane: null, fuel_type: 'diesel' },
      { id: 'hvo', label: 'HVO (XTL)', grade: 'XTL', octane: null, fuel_type: 'diesel' },
    ],
  },
  taxes: { types: [], names: {} },
  lez: { scheme: null, name: null, url: null },
  insurance: { policy_types: [], coverage_keys: [], no_claims: null },
  tolls: { systems: [] },
  default_reminder_packs: [],
  data_sources: { recalls: [], fuel_prices: null },
  registration_certificate: { markers: [], plate_patterns: [], energy_codes: {}, national_categories: [] },
  sources: [],
}

/** A profile with pump names but no octane scale and the US diesel grades. */
const AKI_PROFILE = {
  ...FR_PROFILE,
  country: 'XX',
  fuel: { octane_scale: 'AKI', diesel_dyed_distinction: true, grades: [] },
}

const presetSelect = (): HTMLSelectElement | null =>
  document.getElementById('fuel_preset') as HTMLSelectElement | null
const labelSelect = (): HTMLSelectElement | null =>
  document.getElementById('fuel_grade') as HTMLSelectElement | null

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
const scaleSelect = (): HTMLSelectElement | null =>
  document.getElementById('octane_scale') as HTMLSelectElement | null
const gradeSelect = (): HTMLSelectElement | null =>
  document.getElementById('diesel_grade') as HTMLSelectElement | null

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  profileState.country = null
  profileState.profile = null
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

describe('FuelRecordForm — EN 16942 fuel grade from the country profile (#211)', () => {
  it('without a country the form is unchanged: no label, octane labelled AKI-or-RON', async () => {
    mockGets(mockVehicle({ fuel_type: 'gasoline' }))
    render(<FuelRecordForm {...DEFAULT_PROPS} />)
    await waitFor(() => expect(octaneInput()).toBeInTheDocument())
    expect(presetSelect()).not.toBeInTheDocument()
    expect(labelSelect()).not.toBeInTheDocument()
    expect(screen.getByText('fuel.octane')).toBeInTheDocument()
    expect(screen.queryByText('fuel.octaneRon')).not.toBeInTheDocument()
  })

  it('a French petrol fill-up offers the pump names; picking SP98 writes E5 and 98 RON', async () => {
    profileState.country = 'FR'
    profileState.profile = FR_PROFILE
    mockGets(mockVehicle({ fuel_type: 'gasoline' }))
    render(
      <FuelRecordForm
        {...DEFAULT_PROPS}
        record={{ id: 21, vin: DEFAULT_PROPS.vin, date: '2026-05-01' } as never}
      />,
    )
    await waitFor(() => expect(presetSelect()).toBeInTheDocument())
    const names = Array.from(presetSelect()!.options).map((o) => o.value)
    expect(names).toEqual(['', 'sp95_e10', 'sp95', 'sp98', 'other'])
    // Only petrol pumps: the diesel names stay out of a petrol fill-up.
    expect(names).not.toContain('gazole')
    // The plain label select is hidden while a pump name can be picked.
    expect(labelSelect()).not.toBeInTheDocument()

    fireEvent.change(presetSelect()!, { target: { value: 'sp98' } })
    await waitFor(() => expect(octaneInput()?.value).toBe('98'))
    // A pump name's octane is on the profile's scale, so it brings the scale.
    expect(scaleSelect()?.value).toBe('RON')
    fireEvent.submit(drawerForm())
    await waitFor(() => expect(mockedApiPut).toHaveBeenCalled())
    const body = mockedApiPut.mock.calls.at(-1)?.[1] as Record<string, unknown>
    expect(body.fuel_grade).toBe('E5')
    expect(body.octane).toBe(98)
    expect(body.octane_scale).toBe('RON')
  })

  it('a French diesel fill-up hides the US on/off-road grade and offers B7 / XTL', async () => {
    profileState.country = 'FR'
    profileState.profile = FR_PROFILE
    mockGets(mockVehicle({ fuel_type: 'diesel' }))
    render(
      <FuelRecordForm
        {...DEFAULT_PROPS}
        record={{ id: 22, vin: DEFAULT_PROPS.vin, date: '2026-05-01' } as never}
      />,
    )
    await waitFor(() => expect(presetSelect()).toBeInTheDocument())
    expect(gradeSelect()).not.toBeInTheDocument()
    expect(octaneInput()).not.toBeInTheDocument()
    expect(Array.from(presetSelect()!.options).map((o) => o.value)).toEqual(['', 'gazole', 'hvo', 'other'])

    fireEvent.change(presetSelect()!, { target: { value: 'hvo' } })
    fireEvent.submit(drawerForm())
    await waitFor(() => expect(mockedApiPut).toHaveBeenCalled())
    const body = mockedApiPut.mock.calls.at(-1)?.[1] as Record<string, unknown>
    expect(body.fuel_grade).toBe('XTL')
    expect(body.diesel_grade).toBeNull()
  })

  it('a profile without pump names shows the plain EN 16942 select for the fuel type', async () => {
    profileState.country = 'XX'
    profileState.profile = AKI_PROFILE
    mockGets(mockVehicle({ fuel_type: 'diesel' }))
    render(<FuelRecordForm {...DEFAULT_PROPS} />)
    await waitFor(() => expect(labelSelect()).toBeInTheDocument())
    expect(presetSelect()).not.toBeInTheDocument()
    expect(Array.from(labelSelect()!.options).map((o) => o.value)).toEqual([
      '', 'B7', 'B10', 'B20', 'B30', 'B100', 'XTL',
    ])
    // diesel_dyed_distinction is true here, so the US grade stays.
    expect(gradeSelect()).toBeInTheDocument()
  })

  it('"Other" reveals the plain select; the pump name is derived back from label + octane', async () => {
    profileState.country = 'FR'
    profileState.profile = FR_PROFILE
    mockGets(mockVehicle({ fuel_type: 'gasoline' }))
    render(
      <FuelRecordForm
        {...DEFAULT_PROPS}
        record={{ id: 23, vin: DEFAULT_PROPS.vin, date: '2026-05-01', fuel_grade: 'E5', octane: 98 } as never}
      />,
    )
    // An edited record's label and octane select the matching pump name.
    await waitFor(() => expect(presetSelect()?.value).toBe('sp98'))

    fireEvent.change(presetSelect()!, { target: { value: 'other' } })
    await waitFor(() => expect(labelSelect()).toBeInTheDocument())
    expect(labelSelect()?.value).toBe('E5')

    // A label chosen by hand that matches no pump name keeps "Other".
    fireEvent.change(octaneInput()!, { target: { value: '100' } })
    await waitFor(() => expect(presetSelect()?.value).toBe('other'))

    // Clearing the label sends null (issue-#108 convention).
    fireEvent.change(labelSelect()!, { target: { value: '' } })
    fireEvent.submit(drawerForm())
    await waitFor(() => expect(mockedApiPut).toHaveBeenCalled())
    const body = mockedApiPut.mock.calls.at(-1)?.[1] as Record<string, unknown>
    expect(body.fuel_grade).toBeNull()
  })

  it('create mode seeds the label from the last fill-up, which selects its pump name', async () => {
    profileState.country = 'FR'
    profileState.profile = FR_PROFILE
    mockGets(mockVehicle({ fuel_type: 'gasoline' }), [{ id: 9, octane: 95, fuel_grade: 'E10' }])
    render(<FuelRecordForm {...DEFAULT_PROPS} />)
    await waitFor(() => expect(presetSelect()?.value).toBe('sp95_e10'))
  })

  it('switching the fuel dispensed to diesel drops a petrol label', async () => {
    profileState.country = 'FR'
    profileState.profile = FR_PROFILE
    mockGets(mockVehicle({ fuel_type: 'gasoline', fuel_type_secondary: 'diesel' } as never))
    render(
      <FuelRecordForm
        {...DEFAULT_PROPS}
        record={{ id: 24, vin: DEFAULT_PROPS.vin, date: '2026-05-01', fuel_type_used: 'gasoline', fuel_grade: 'E10', octane: 95 } as never}
      />,
    )
    await waitFor(() => expect(presetSelect()?.value).toBe('sp95_e10'))

    const fuelTypeSelect = document.getElementById('fuel_type_used') as HTMLSelectElement
    fireEvent.change(fuelTypeSelect, { target: { value: 'diesel' } })
    await waitFor(() => expect(presetSelect()?.value).toBe(''))

    fireEvent.submit(drawerForm())
    await waitFor(() => expect(mockedApiPut).toHaveBeenCalled())
    const body = mockedApiPut.mock.calls.at(-1)?.[1] as Record<string, unknown>
    expect(body.fuel_grade).toBeNull()
    expect(body.fuel_type_used).toBe('diesel')
  })
})

describe('FuelRecordForm — the octane scale travels with its number (B4)', () => {
  it('a new French fill-up defaults to RON, labels the field RON and sends the pair', async () => {
    profileState.country = 'FR'
    profileState.profile = FR_PROFILE
    mockGets(mockVehicle({ fuel_type: 'gasoline' }))
    render(<FuelRecordForm {...DEFAULT_PROPS} />)
    await waitFor(() => expect(scaleSelect()?.value).toBe('RON'))
    expect(screen.getByText('fuel.octaneRon')).toBeInTheDocument()
  })

  it('without a profile a new fill-up records no scale', async () => {
    mockGets(mockVehicle({ fuel_type: 'gasoline' }))
    render(<FuelRecordForm {...DEFAULT_PROPS} />)
    await waitFor(() => expect(scaleSelect()).toBeInTheDocument())
    expect(scaleSelect()?.value).toBe('')
  })

  it('a new fill-up seeded from the last one takes its scale with its octane', async () => {
    profileState.country = 'FR'
    profileState.profile = FR_PROFILE
    mockGets(mockVehicle({ fuel_type: 'gasoline' }), [{ id: 9, octane: 91, octane_scale: 'AKI' }])
    render(<FuelRecordForm {...DEFAULT_PROPS} />)
    await waitFor(() => expect(octaneInput()?.value).toBe('91'))
    await waitFor(() => expect(scaleSelect()?.value).toBe('AKI'))
  })

  it('editing the notes after a move to France keeps the stored AKI pair', async () => {
    profileState.country = 'FR'
    profileState.profile = FR_PROFILE
    mockGets(mockVehicle({ fuel_type: 'gasoline' }))
    render(
      <FuelRecordForm
        {...DEFAULT_PROPS}
        record={{ id: 5, vin: DEFAULT_PROPS.vin, date: '2026-05-01', octane: 91, octane_scale: 'AKI' } as never}
      />,
    )
    await waitFor(() => expect(scaleSelect()?.value).toBe('AKI'))
    expect(screen.queryByText('fuel.octaneRon')).not.toBeInTheDocument()
    fireEvent.change(document.getElementById('notes')!, { target: { value: 'moved to Lyon' } })
    fireEvent.submit(drawerForm())
    await waitFor(() => expect(mockedApiPut).toHaveBeenCalled())
    const body = mockedApiPut.mock.calls.at(-1)?.[1] as Record<string, unknown>
    expect(body.octane).toBe(91)
    expect(body.octane_scale).toBe('AKI')
  })

  it('a legacy fill-up with no scale stays without one on edit, even in France', async () => {
    profileState.country = 'FR'
    profileState.profile = FR_PROFILE
    mockGets(mockVehicle({ fuel_type: 'gasoline' }))
    render(
      <FuelRecordForm
        {...DEFAULT_PROPS}
        record={{ id: 5, vin: DEFAULT_PROPS.vin, date: '2026-05-01', octane: 95, octane_scale: null } as never}
      />,
    )
    await waitFor(() => expect(octaneInput()?.value).toBe('95'))
    expect(scaleSelect()?.value).toBe('')
    fireEvent.submit(drawerForm())
    await waitFor(() => expect(mockedApiPut).toHaveBeenCalled())
    const body = mockedApiPut.mock.calls.at(-1)?.[1] as Record<string, unknown>
    expect(body.octane).toBe(95)
    expect(body.octane_scale).toBeNull()
  })

  it('picking a scale on a legacy fill-up sends it', async () => {
    mockGets(mockVehicle({ fuel_type: 'gasoline' }))
    render(
      <FuelRecordForm
        {...DEFAULT_PROPS}
        record={{ id: 5, vin: DEFAULT_PROPS.vin, date: '2026-05-01', octane: 87, octane_scale: null } as never}
      />,
    )
    await waitFor(() => expect(scaleSelect()).toBeInTheDocument())
    fireEvent.change(scaleSelect()!, { target: { value: 'AKI' } })
    fireEvent.submit(drawerForm())
    await waitFor(() => expect(mockedApiPut).toHaveBeenCalled())
    const body = mockedApiPut.mock.calls.at(-1)?.[1] as Record<string, unknown>
    expect(body.octane_scale).toBe('AKI')
  })
})
