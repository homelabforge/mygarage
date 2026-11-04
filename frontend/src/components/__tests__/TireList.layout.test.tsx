/**
 * The tire screens follow the vehicle's wheel layout (#272).
 *
 * Real English here, not the global key mock: the chips are asserted by the
 * names a rider actually reads, so "Front" and "Rear Left Inner" have to come
 * out of the shipped bundle.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'

import { FOUR_LAYOUT, type TireListLayout } from '../../__tests__/factories'

vi.mock('react-i18next', async () => (await import('@/__tests__/i18nEn')).reactI18nextEn())

const useTiresMock = vi.fn()
const useCreateAndMountTireMock = vi.fn()
const useMountTireMock = vi.fn()
const noop = () => ({ mutate: vi.fn(), isPending: false })

vi.mock('../../hooks/queries/useTires', () => ({
  useTires: () => useTiresMock(),
  useCreateTire: () => noop(),
  useCreateAndMountTire: () => useCreateAndMountTireMock(),
  useUpdateTire: () => noop(),
  useMountTire: () => useMountTireMock(),
  useDismountTire: () => noop(),
  useRestoreTire: () => noop(),
  useRetireTire: () => noop(),
  useRotateTires: () => noop(),
  useAddTireReading: () => noop(),
  useDeleteTire: () => noop(),
  useDeleteTireReading: () => noop(),
  useTireSets: () => ({ data: { sets: [], total: 0 }, isLoading: false, error: null }),
  useCreateTireSet: () => noop(),
  useUpdateTireSet: () => noop(),
  useDeleteTireSet: () => noop(),
  useMountTireSet: () => noop(),
}))

vi.mock('../../hooks/queries/useOdometerRecords', () => ({
  useNearestOdometer: () => ({ data: undefined, isSuccess: false }),
}))

vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}))

vi.mock('../../hooks/useUnitPreference', () => {
  const unitPreference = () => ({
    system: 'metric',
    showBoth: false,
    gallonStandard: 'us',
    units: {
      consumption: 'l_100km',
      distance: 'km',
      length: 'm',
      mass: 'kg',
      pressure: 'kpa',
      secondary_gallon: 'us',
      speed: 'kmh',
      temperature: 'c',
      torque: 'nm',
      tread: 'mm',
      volume: 'L',
    },
  })
  return { useUnitPreference: unitPreference, useAccountUnitPreference: unitPreference }
})

import TireList from '../TireList'

const VIN = '1HGCM82633A004352'

const TWO: TireListLayout = { positions: ['F', 'R'], rotates: false, wheel_layout: 'two' }
const DUALLY: TireListLayout = {
  positions: ['FL', 'FR', 'RLO', 'RLI', 'RRI', 'RRO', 'SPARE'],
  rotates: false,
  wheel_layout: 'dually',
}

const tireAt = (id: number, position: string | null, brand = `Tire ${id}`) => ({
  id,
  vin: VIN,
  position,
  brand,
  model_name: null,
  size: null,
  dot_code: null,
  tread_depth_mm: '7.50',
  pressure_kpa: '240.00',
  min_tread_mm: '3.00',
  notes: null,
  below_threshold: false,
  projected_km_remaining: null,
  projected_wear_date: null,
  readings: [],
  mount_periods: [],
})

const setList = (layout: TireListLayout, tires: unknown[]): void => {
  useTiresMock.mockReturnValue({
    data: { tires, total: tires.length, ...layout },
    isLoading: false,
    error: null,
  })
}

const drawer = () => {
  const dialogs = screen.getAllByRole('dialog')
  return within(dialogs[dialogs.length - 1])
}

/** The text of every chip in the add form's position row, in order. */
const addFormChips = (): string[] => {
  fireEvent.click(screen.getByRole('button', { name: 'Add Tire' }))
  const group = screen.getByRole('group', { name: 'Position' })
  return Array.from(group.children).map((chip) => chip.textContent ?? '')
}

describe('TireList follows the wheel layout', () => {
  beforeEach(() => {
    useCreateAndMountTireMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useMountTireMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
  })

  it('a two-wheeler adds at Front or Rear only, and has no Rotate button', () => {
    setList(TWO, [])
    render(<TireList vin={VIN} />)
    expect(screen.queryByRole('button', { name: 'Rotate' })).not.toBeInTheDocument()
    expect(addFormChips()).toEqual(['Front', 'Rear', 'In storage'])
  })

  it('a two-wheeler with both corners taken adds into storage', () => {
    setList(TWO, [tireAt(1, 'F'), tireAt(2, 'R')])
    render(<TireList vin={VIN} />)
    fireEvent.click(screen.getByRole('button', { name: 'Add Tire' }))
    expect(within(screen.getByRole('group', { name: 'Position' })).getByRole('button', { name: 'In storage' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
  })

  it('a two-wheeler adds at its first free corner', () => {
    const createAndMount = vi.fn()
    useCreateAndMountTireMock.mockReturnValue({ mutate: createAndMount, isPending: false })
    setList(TWO, [tireAt(1, 'F')])
    render(<TireList vin={VIN} />)
    fireEvent.click(screen.getByRole('button', { name: 'Add Tire' }))
    expect(within(screen.getByRole('group', { name: 'Position' })).getByRole('button', { name: 'Rear' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    fireEvent.click(drawer().getByRole('button', { name: 'Save' }))
    expect(createAndMount.mock.calls[0][0]).toMatchObject({ position: 'R' })
  })

  it('a tire left at FL on a two-wheeler is flagged and sorts after Front and Rear', () => {
    // Server order puts it first, so only the sort can move it.
    setList(TWO, [tireAt(1, 'FL', 'Old car tire'), tireAt(2, 'R', 'Rear tire'), tireAt(3, 'F', 'Front tire')])
    render(<TireList vin={VIN} />)
    const opens = screen.getAllByRole('button', { name: /^View reading history for / })
    expect(opens.map((open) => open.textContent)).toEqual([
      'View reading history for Front',
      'View reading history for Rear',
      'View reading history for Front Left',
    ])
    const cards = opens.map((open) => open.closest('.rounded-card') as HTMLElement)
    expect(within(cards[2]).getByText('Not on this wheel layout')).toBeInTheDocument()
    expect(within(cards[0]).queryByText('Not on this wheel layout')).not.toBeInTheDocument()
    expect(within(cards[1]).queryByText('Not on this wheel layout')).not.toBeInTheDocument()
  })

  it('mounting a stored tire on a two-wheeler offers the free layout corners and picks the first', () => {
    const mount = vi.fn()
    useMountTireMock.mockReturnValue({ mutate: mount, isPending: false })
    // FL is taken by an off-layout tire, which must not make Front look taken.
    setList(TWO, [tireAt(1, 'FL'), tireAt(2, null)])
    render(<TireList vin={VIN} />)
    fireEvent.click(screen.getByRole('button', { name: 'Mount' }))
    const chips = drawer()
      .getAllByRole('button')
      .filter((button) => button.hasAttribute('aria-pressed'))
    expect(chips.map((chip) => chip.textContent)).toEqual(['Front', 'Rear'])
    expect(drawer().getByRole('button', { name: 'Front' })).toHaveAttribute('aria-pressed', 'true')
    fireEvent.click(drawer().getAllByRole('button', { name: 'Mount' }).at(-1)!)
    expect(mount.mock.calls[0][0]).toMatchObject({ tireId: 2, position: 'F' })
  })

  it('a car keeps its Rotate button', () => {
    setList(FOUR_LAYOUT, [tireAt(1, 'FL'), tireAt(2, 'FR'), tireAt(3, 'RL'), tireAt(4, 'RR')])
    render(<TireList vin={VIN} />)
    expect(screen.getByRole('button', { name: 'Rotate' })).toBeEnabled()
  })

  it('a dually adds at six named corners plus the spare', () => {
    setList(DUALLY, [])
    render(<TireList vin={VIN} />)
    expect(screen.queryByRole('button', { name: 'Rotate' })).not.toBeInTheDocument()
    expect(addFormChips()).toEqual([
      'Front Left',
      'Front Right',
      'Rear Left Outer',
      'Rear Left Inner',
      'Rear Right Inner',
      'Rear Right Outer',
      'Spare',
      'In storage',
    ])
  })

  it('says which wheel layout the list follows, by name', () => {
    setList(TWO, [])
    render(<TireList vin={VIN} />)
    expect(
      screen.getByText('Wheel layout: Two wheels (front and rear). Change it under Vehicle Details.'),
    ).toBeInTheDocument()
  })
})
