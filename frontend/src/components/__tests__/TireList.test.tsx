import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

// Mock the query hooks so this stays a unit test - no QueryClient/api wiring.
const useTiresMock = vi.fn()
const useUpsertTireMock = vi.fn()
const useAddTireReadingMock = vi.fn()

vi.mock('../../hooks/queries/useTires', () => ({
  useTires: () => useTiresMock(),
  useUpsertTire: () => useUpsertTireMock(),
  useAddTireReading: () => useAddTireReadingMock(),
  useDeleteTire: () => ({ mutate: vi.fn(), isPending: false }),
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
  beforeEach(() => {
    useUpsertTireMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useAddTireReadingMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
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

  it('offers only unoccupied positions when adding', () => {
    render(<TireList vin="1HGCM82633A004352" />)
    fireEvent.click(screen.getByText('tireList.add'))

    const select = screen.getByLabelText('tireList.position') as HTMLSelectElement
    const values = Array.from(select.querySelectorAll('option')).map((o) => o.value)
    expect(values).not.toContain('FL')
    expect(values).toContain('FR')
  })
})
