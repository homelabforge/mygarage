import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, waitFor, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { render } from '../../__tests__/test-utils'
import FuelRecordForm from '../FuelRecordForm'
import type { Vehicle } from '../../types/vehicle'

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

// Requires AuthProvider otherwise — same mock pattern as ServiceVisitForm.test.tsx
vi.mock('../../hooks/useUnitPreference', () => ({
  useUnitPreference: () => ({ system: 'metric', showBoth: false }),
}))

vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({ user: null }),
}))

const timeFormatMock = vi.hoisted(() => ({ value: '24h' as '12h' | '24h' }))
vi.mock('../../hooks/useTimeFormat', () => ({
  useTimeFormat: () => ({ timeFormat: timeFormatMock.value }),
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

const DEFAULT_PROPS = {
  vin: 'TEST12345678901234',
  onClose: vi.fn(),
  onSuccess: vi.fn(),
}

describe('FuelRecordForm — DEF tank level visibility (diesel-only gate)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows the DEF tank level section for a diesel vehicle', async () => {
    mockedApiGet.mockResolvedValue({ data: mockVehicle({ fuel_type: 'diesel' }) })

    render(<FuelRecordForm {...DEFAULT_PROPS} />)

    await waitFor(() => {
      expect(screen.getByText('fuel.defTankLevel')).toBeInTheDocument()
    })
  })

  it('hides the DEF tank level section for a non-diesel vehicle even with a legacy DEF tank capacity set', async () => {
    // Pre-hardening behavior showed this section whenever def_tank_capacity_liters > 0,
    // regardless of fuel type. That arm is now unreachable for new data (the
    // server 400s the write) and the UI shouldn't invite it either.
    mockedApiGet.mockResolvedValue({
      data: mockVehicle({ fuel_type: 'gasoline', def_tank_capacity_liters: '19.0' }),
    })

    render(<FuelRecordForm {...DEFAULT_PROPS} />)

    // Wait for the vehicle fetch effect to settle before asserting absence.
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())
    expect(screen.queryByText('fuel.defTankLevel')).not.toBeInTheDocument()
  })

  it('hides the DEF tank level section for a plain non-diesel vehicle', async () => {
    mockedApiGet.mockResolvedValue({ data: mockVehicle({ fuel_type: 'gasoline' }) })

    render(<FuelRecordForm {...DEFAULT_PROPS} />)

    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())
    expect(screen.queryByText('fuel.defTankLevel')).not.toBeInTheDocument()
  })
})

const REC = { id: 1, vin: DEFAULT_PROPS.vin, date: '2026-04-30', filled_at: '2026-04-30T22:00' }
const timeInput = () => document.getElementById('filled_at_time') as HTMLInputElement
const dateInput = (id: string) => document.getElementById(id) as HTMLInputElement

describe('FuelRecordForm — fill-up time (issue #109 / time-format)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    timeFormatMock.value = '24h'
    // "More details" expansion persists in localStorage; clear it so a click
    // reliably OPENS (not toggles-closed) across tests.
    localStorage.removeItem('fuel_form:more_details_expanded')
  })

  async function openMoreDetails(user: ReturnType<typeof userEvent.setup>) {
    await user.click(screen.getByText('fuel.moreDetails')) // collapsed by default
  }

  it('24h: submits filled_at=<record date>T<time> from a RAW, never-blurred time', async () => {
    const user = userEvent.setup()
    mockedApiGet.mockResolvedValue({ data: mockVehicle({ fuel_type: 'gasoline' }) })
    const { container } = render(<FuelRecordForm {...DEFAULT_PROPS} />)
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())

    fireEvent.change(dateInput('date'), { target: { value: '2026-04-30' } }) // required top field
    await openMoreDetails(user)
    // Raw compact value, NO blur — the field still holds "2200" at submit time.
    fireEvent.change(timeInput(), { target: { value: '2200' } })
    fireEvent.submit(container.querySelector('form') as HTMLFormElement)

    await waitFor(() => expect(mockedApiPost).toHaveBeenCalled())
    const body = mockedApiPost.mock.calls.at(-1)?.[1] as Record<string, unknown>
    expect(body.filled_at).toBe('2026-04-30T22:00')
  })

  it('12h: hour + explicit PM submits the correct canonical time', async () => {
    timeFormatMock.value = '12h'
    const user = userEvent.setup()
    mockedApiGet.mockResolvedValue({ data: mockVehicle({ fuel_type: 'gasoline' }) })
    const { container } = render(<FuelRecordForm {...DEFAULT_PROPS} />)
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())

    fireEvent.change(dateInput('date'), { target: { value: '2026-04-30' } })
    await openMoreDetails(user)
    fireEvent.change(timeInput(), { target: { value: '2:30' } })
    fireEvent.click(screen.getByRole('button', { name: 'PM' }))
    fireEvent.submit(container.querySelector('form') as HTMLFormElement)

    await waitFor(() => expect(mockedApiPost).toHaveBeenCalled())
    const body = mockedApiPost.mock.calls.at(-1)?.[1] as Record<string, unknown>
    expect(body.filled_at).toBe('2026-04-30T14:30')
  })

  it('12h: 12:00 AM maps to midnight (00:00)', async () => {
    timeFormatMock.value = '12h'
    const user = userEvent.setup()
    mockedApiGet.mockResolvedValue({ data: mockVehicle({ fuel_type: 'gasoline' }) })
    const { container } = render(<FuelRecordForm {...DEFAULT_PROPS} />)
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())

    fireEvent.change(dateInput('date'), { target: { value: '2026-04-30' } })
    await openMoreDetails(user)
    fireEvent.change(timeInput(), { target: { value: '12:00' } })
    fireEvent.click(screen.getByRole('button', { name: 'AM' }))
    fireEvent.submit(container.querySelector('form') as HTMLFormElement)

    await waitFor(() => expect(mockedApiPost).toHaveBeenCalled())
    const body = mockedApiPost.mock.calls.at(-1)?.[1] as Record<string, unknown>
    expect(body.filled_at).toBe('2026-04-30T00:00')
  })

  it('sends filled_at=null when clearing an existing timestamp (so the clear persists)', async () => {
    const user = userEvent.setup()
    mockedApiGet.mockResolvedValue({ data: mockVehicle({ fuel_type: 'gasoline' }) })
    const { container } = render(<FuelRecordForm {...DEFAULT_PROPS} record={REC as never} />)
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())

    await openMoreDetails(user)
    fireEvent.change(timeInput(), { target: { value: '' } })
    fireEvent.submit(container.querySelector('form') as HTMLFormElement)

    await waitFor(() => expect(mockedApiPut).toHaveBeenCalled())
    const body = mockedApiPut.mock.calls.at(-1)?.[1] as Record<string, unknown>
    expect(body.filled_at).toBeNull()  // explicit null clears; undefined would preserve
  })

  it('preserves the stored filled_at verbatim on edit when the time is untouched (R1-H2)', async () => {
    const user = userEvent.setup()
    mockedApiGet.mockResolvedValue({ data: mockVehicle({ fuel_type: 'gasoline' }) })
    const { container } = render(<FuelRecordForm {...DEFAULT_PROPS} record={REC as never} />)
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())

    await openMoreDetails(user)
    // Do NOT touch the time; submit. The exact stored timestamp must survive.
    fireEvent.submit(container.querySelector('form') as HTMLFormElement)

    await waitFor(() => expect(mockedApiPut).toHaveBeenCalled())
    const body = mockedApiPut.mock.calls.at(-1)?.[1] as Record<string, unknown>
    expect(body.filled_at).toBe('2026-04-30T22:00')
  })

  it('blocks submission (no API call) on an invalid non-empty time — visible input not silently lost (Codex R1-H1)', async () => {
    const user = userEvent.setup()
    mockedApiGet.mockResolvedValue({ data: mockVehicle({ fuel_type: 'gasoline' }) })
    const { container } = render(<FuelRecordForm {...DEFAULT_PROPS} />)
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())
    fireEvent.change(dateInput('date'), { target: { value: '2026-04-30' } })
    await openMoreDetails(user)
    fireEvent.change(timeInput(), { target: { value: '25:00' } }) // invalid, non-empty
    fireEvent.submit(container.querySelector('form') as HTMLFormElement)
    // Error surfaces (the i18n test mock renders the KEY) and no create fires.
    await screen.findByText('fuel.invalidFilledTime')
    expect(mockedApiPost).not.toHaveBeenCalled()
  })

  it('seeds the time control from an existing record (24h)', async () => {
    const user = userEvent.setup()
    mockedApiGet.mockResolvedValue({ data: mockVehicle({ fuel_type: 'gasoline' }) })
    render(<FuelRecordForm {...DEFAULT_PROPS} record={REC as never} />)
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())
    await openMoreDetails(user)
    expect(timeInput().value).toBe('22:00')
  })
})

describe('FuelRecordForm — station round-trip (issue #108)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.removeItem('fuel_form:more_details_expanded')
  })

  // A station picked from the address book: FK set, freetext nulled by the
  // backend, resolved name carried by `station_name`.
  const PICKED = {
    ...REC,
    station_address_book_id: 7,
    station_name_freetext: null,
    station_name: 'Exxon Mobil #42',
  }
  // A one-time visit: freetext only, no FK.
  const ONE_TIME = {
    ...REC,
    station_address_book_id: null,
    station_name_freetext: 'Roadside Pumps',
    station_name: 'Roadside Pumps',
  }

  const stationInput = () =>
    document.getElementById('station_name_freetext') as HTMLInputElement
  const oneTimeCheckbox = () =>
    document.getElementById('one_time_visit') as HTMLInputElement

  async function renderWithRecord(record: object) {
    const user = userEvent.setup()
    mockedApiGet.mockResolvedValue({ data: mockVehicle({ fuel_type: 'gasoline' }) })
    const utils = render(<FuelRecordForm {...DEFAULT_PROPS} record={record as never} />)
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())
    await user.click(screen.getByText('fuel.moreDetails')) // collapsed by default
    return utils
  }

  const putPayload = () => mockedApiPut.mock.calls[0][1] as Record<string, unknown>

  it('seeds the station box from a picked address-book station', async () => {
    await renderWithRecord(PICKED)
    expect(stationInput().value).toBe('Exxon Mobil #42')
  })

  it('seeds the station box from a one-time-visit freetext station', async () => {
    await renderWithRecord(ONE_TIME)
    expect(stationInput().value).toBe('Roadside Pumps')
  })

  it('checks one-time visit for a record that IS one', async () => {
    // The flag is not stored — it is implied by freetext-without-FK. Seeding a
    // flat false left this unchecked, so editing promoted the stop into the
    // address book the user had kept it out of.
    await renderWithRecord(ONE_TIME)
    expect(oneTimeCheckbox().checked).toBe(true)
  })

  it('leaves one-time visit unchecked for an address-book station', async () => {
    await renderWithRecord(PICKED)
    expect(oneTimeCheckbox().checked).toBe(false)
  })

  it('drops the stale FK when the user retypes over a picked station', async () => {
    const { container } = await renderWithRecord(PICKED)

    fireEvent.change(stationInput(), { target: { value: 'Shell Highway 6' } })
    fireEvent.submit(container.querySelector('form') as HTMLFormElement)

    await waitFor(() => expect(mockedApiPut).toHaveBeenCalled())
    expect(putPayload().station_name_freetext).toBe('Shell Highway 6')
    expect(putPayload().station_address_book_id).toBeNull()
  })

  it('restores the link when the typed text returns to the station name', async () => {
    // Otherwise a stray keystroke, corrected, still submits a cleared FK and
    // silently re-creates the station on save.
    const { container } = await renderWithRecord(PICKED)

    fireEvent.change(stationInput(), { target: { value: 'Exxon Mobil #4' } })
    fireEvent.change(stationInput(), { target: { value: 'Exxon Mobil #42' } })
    fireEvent.submit(container.querySelector('form') as HTMLFormElement)

    await waitFor(() => expect(mockedApiPut).toHaveBeenCalled())
    expect(putPayload().station_address_book_id).toBe(7)
  })

  it('keeps the FK when the user edits an unrelated field', async () => {
    const { container } = await renderWithRecord(PICKED)

    fireEvent.change(dateInput('date'), { target: { value: '2026-05-01' } })
    fireEvent.submit(container.querySelector('form') as HTMLFormElement)

    await waitFor(() => expect(mockedApiPut).toHaveBeenCalled())
    expect(putPayload().station_address_book_id).toBe(7)
  })
})
