import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'

// Mock the query hooks so this stays a unit test - no QueryClient/api wiring.
const useTiresMock = vi.fn()
const useUpsertTireMock = vi.fn()
const useAddTireReadingMock = vi.fn()
const useDeleteTireMock = vi.fn()

vi.mock('../../hooks/queries/useTires', () => ({
  useTires: () => useTiresMock(),
  useUpsertTire: () => useUpsertTireMock(),
  useAddTireReading: () => useAddTireReadingMock(),
  useDeleteTire: () => useDeleteTireMock(),
}))

vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}))

// useUnitPreference calls useAuth, which throws outside an AuthProvider, and the
// shared renderer does not supply one. Imperial is what exercises conversion.
vi.mock('../../hooks/useUnitPreference', () => ({
  useUnitPreference: () => ({ system: 'imperial', showBoth: false }),
}))

import TireList from '../TireList'

const STORED_FL_TIRE = {
  id: 1,
  vin: '1HGCM82633A004352',
  position: 'FL' as const,
  brand: 'Michelin',
  model_name: 'Pilot Sport 4',
  size: '225/45R17',
  dot_code: '2324',
  tread_depth_mm: '7.50',
  pressure_kpa: '240.00',
  min_tread_mm: '3.00',
  notes: null,
  below_threshold: false,
  projected_km_remaining: null,
  projected_wear_date: null,
  readings: [],
}

describe('TireList', () => {
  // The window.confirm spy in the delete tests would otherwise leak into every
  // test that runs after it.
  afterEach(() => {
    vi.restoreAllMocks()
  })

  beforeEach(() => {
    useUpsertTireMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useAddTireReadingMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useDeleteTireMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useTiresMock.mockReturnValue({
      data: { tires: [STORED_FL_TIRE], total: 1 },
      isLoading: false,
      error: null,
    })
  })

  it('prefills from the stored tire so a re-save does not blank it', () => {
    const mutate = vi.fn()
    useUpsertTireMock.mockReturnValue({ mutate, isPending: false })

    render(<TireList vin="1HGCM82633A004352" />)
    fireEvent.click(screen.getByLabelText('tireList.edit'))
    fireEvent.click(screen.getByText('common:save'))

    expect(mutate.mock.calls[0][0]).toMatchObject({
      position: 'FL',
      brand: 'Michelin',
      model_name: 'Pilot Sport 4',
      size: '225/45R17',
      dot_code: '2324',
    })
  })

  it('labels the reading odometer in miles for an imperial user', () => {
    render(<TireList vin="1HGCM82633A004352" />)
    fireEvent.click(screen.getByText('tireList.addReading'))

    expect(screen.getByLabelText('tireList.odometerMi')).toBeInTheDocument()
    expect(screen.queryByLabelText('tireList.odometerKm')).not.toBeInTheDocument()
  })

  it('submits canonical km when the user works in miles', () => {
    const mutate = vi.fn()
    useAddTireReadingMock.mockReturnValue({ mutate, isPending: false })

    render(<TireList vin="1HGCM82633A004352" />)
    fireEvent.click(screen.getByText('tireList.addReading'))
    fireEvent.change(screen.getByLabelText('tireList.odometerMi'), {
      target: { value: '100' },
    })
    fireEvent.click(screen.getByText('common:save'))

    // milesToKm uses factor 1.60934 and rounds to 2 decimals, so 100 mi is 160.93.
    expect(mutate.mock.calls[0][0].odometer_km).toBe(160.93)
  })

  it('sends null, not undefined, when pressure is cleared', () => {
    const mutate = vi.fn()
    useUpsertTireMock.mockReturnValue({ mutate, isPending: false })

    render(<TireList vin="1HGCM82633A004352" />)
    fireEvent.click(screen.getByLabelText('tireList.edit'))
    fireEvent.change(screen.getByLabelText('tireList.pressureWithUnit'), {
      target: { value: '' },
    })
    fireEvent.click(screen.getByText('common:save'))

    // undefined would be dropped from the JSON body and the partial update
    // would then preserve the old pressure instead of clearing it.
    expect(mutate.mock.calls[0][0]).toHaveProperty('pressure_kpa', null)
  })

  it('shows stored kPa as PSI in the edit form', () => {
    render(<TireList vin="1HGCM82633A004352" />)
    fireEvent.click(screen.getByLabelText('tireList.edit'))

    // 240 kPa -> 34.81 PSI
    const input = screen.getByLabelText('tireList.pressureWithUnit') as HTMLInputElement
    expect(Number(input.value)).toBeCloseTo(34.81, 1)
  })

  it('opens the tire form in a drawer, titled by intent', () => {
    render(<TireList vin="1HGCM82633A004352" />)
    // Nothing is open until an intent is chosen.
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

    fireEvent.click(screen.getByText('tireList.add'))
    expect(screen.getByRole('dialog')).toHaveAccessibleName('tireList.addTitle')

    fireEvent.click(screen.getByText('common:cancel'))
    fireEvent.click(screen.getByLabelText('tireList.edit'))
    expect(screen.getByRole('dialog')).toHaveAccessibleName('tireList.editTitleNamed')
  })

  it('opens the reading form in its own drawer, named for the position', () => {
    render(<TireList vin="1HGCM82633A004352" />)
    fireEvent.click(screen.getByText('tireList.addReading'))

    // Only one drawer at a time, so `common:save` stays unambiguous.
    expect(screen.getByRole('dialog')).toHaveAccessibleName('tireList.readingTitle')
    expect(screen.getAllByText('common:save')).toHaveLength(1)
  })

  it('shows every position but only lets you pick the free ones when adding', () => {
    render(<TireList vin="1HGCM82633A004352" />)
    fireEvent.click(screen.getByText('tireList.add'))

    const group = screen.getByRole('group', { name: 'tireList.position' })
    // FL is taken by STORED_FL_TIRE. It still renders — that is the point of
    // the toggles over a select — but as an inert span rather than a button.
    expect(within(group).getByText('FL').tagName).toBe('SPAN')
    expect(within(group).getByText('FR').tagName).toBe('BUTTON')
  })

  it('names positions in full on the card but keeps short codes on the toggles', () => {
    render(<TireList vin="1HGCM82633A004352" />)
    // The card heading carries the translatable name, not the raw enum.
    expect(screen.getByText('tireList.positions.FL')).toBeInTheDocument()

    // The toggle row stays compact — five full names would not fit.
    fireEvent.click(screen.getByText('tireList.add'))
    const group = screen.getByRole('group', { name: 'tireList.position' })
    expect(within(group).getByText('FL')).toBeInTheDocument()
    expect(within(group).queryByText('tireList.positions.FL')).not.toBeInTheDocument()
  })

  it('keeps delete out of the card and offers it only while editing', () => {
    const mutate = vi.fn()
    useDeleteTireMock.mockReturnValue({ mutate, isPending: false })
    vi.spyOn(window, 'confirm').mockReturnValue(true)

    render(<TireList vin="1HGCM82633A004352" />)
    // Not on the card, where it sat next to the routine controls.
    expect(screen.queryByText('common:delete')).not.toBeInTheDocument()

    // Nor in the Add drawer — there is nothing to delete yet.
    fireEvent.click(screen.getByText('tireList.add'))
    expect(screen.queryByText('common:delete')).not.toBeInTheDocument()
    fireEvent.click(screen.getByText('common:cancel'))

    fireEvent.click(screen.getByLabelText('tireList.edit'))
    fireEvent.click(screen.getByText('common:delete'))
    expect(mutate.mock.calls[0][0]).toBe(1)
  })

  it('does not delete when the confirm is dismissed', () => {
    const mutate = vi.fn()
    useDeleteTireMock.mockReturnValue({ mutate, isPending: false })
    vi.spyOn(window, 'confirm').mockReturnValue(false)

    render(<TireList vin="1HGCM82633A004352" />)
    fireEvent.click(screen.getByLabelText('tireList.edit'))
    fireEvent.click(screen.getByText('common:delete'))

    expect(mutate).not.toHaveBeenCalled()
  })

  it('locks the position while editing', () => {
    render(<TireList vin="1HGCM82633A004352" />)
    fireEvent.click(screen.getByLabelText('tireList.edit'))

    const group = screen.getByRole('group', { name: 'tireList.position' })
    // Nothing is clickable, so the position cannot be moved out from under a
    // tire whose readings are already keyed to it.
    expect(within(group).queryAllByRole('button')).toHaveLength(0)
    expect(within(group).getByText('FL')).toHaveClass('bg-(--accent-soft)')
  })

  it('selects a free position when its toggle is pressed', () => {
    const mutate = vi.fn()
    useUpsertTireMock.mockReturnValue({ mutate, isPending: false })

    render(<TireList vin="1HGCM82633A004352" />)
    fireEvent.click(screen.getByText('tireList.add'))

    const group = screen.getByRole('group', { name: 'tireList.position' })
    fireEvent.click(within(group).getByText('RR'))
    fireEvent.click(screen.getByText('common:save'))

    expect(mutate.mock.calls[0][0]).toMatchObject({ position: 'RR' })
  })
})
