/**
 * Rotate, retire and create-into-storage: the three flows that had no UI.
 *
 * All three endpoints shipped with the mount-period model, all three had a
 * query hook, and none of them had a caller. `useRotateTires`, `useRetireTire`
 * and `useCreateTire` each had exactly zero consumers in `src/`, and there was
 * not one `tireList.rotate*` or `tireList.retire*` translation key. The e2e
 * suite exercised all three, which is why nothing caught it: it drove them
 * through the API, so it proved the endpoints worked rather than that anyone
 * could reach them.
 *
 * These tests go through the rendered controls for that reason. A test that
 * called the hook directly would reproduce the original blind spot exactly.
 */

import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'

const useTiresMock = vi.fn()
const useCreateTireMock = vi.fn()
const useCreateAndMountTireMock = vi.fn()
const useRetireTireMock = vi.fn()
const useRotateTiresMock = vi.fn()
const useDeleteTireMock = vi.fn()
const useTireSetsMock = vi.fn()
const useCreateTireSetMock = vi.fn()
const useMountTireSetMock = vi.fn()
const useUpdateTireMock = vi.fn()
const noop = () => ({ mutate: vi.fn(), isPending: false })

// Every mutation gets its OWN mock here, unlike TireList.test.tsx which aliases
// several onto one. The distinction is the whole subject: retire must not be
// delete, and create-into-storage must not be create-and-mount.
vi.mock('../../hooks/queries/useTires', () => ({
  useTires: () => useTiresMock(),
  useCreateTire: () => useCreateTireMock(),
  useCreateAndMountTire: () => useCreateAndMountTireMock(),
  useUpdateTire: () => useUpdateTireMock(),
  useMountTire: () => noop(),
  useDismountTire: () => noop(),
  useRetireTire: () => useRetireTireMock(),
  useRotateTires: () => useRotateTiresMock(),
  useAddTireReading: () => noop(),
  useDeleteTire: () => useDeleteTireMock(),
  useTireSets: () => useTireSetsMock(),
  useCreateTireSet: () => useCreateTireSetMock(),
  useUpdateTireSet: () => noop(),
  useDeleteTireSet: () => noop(),
  useMountTireSet: () => useMountTireSetMock(),
}))

vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}))

// Metric, so the odometer fields submit what is typed and the assertions below
// are about the moves rather than about a conversion. Conversion has its own
// coverage in TireList.metric.test.tsx.
vi.mock('../../hooks/useUnitPreference', () => ({
  useUnitPreference: () => ({
    system: 'metric',
    showBoth: false,
    gallonStandard: 'us',
    // METRIC_PRESET exactly as `/api/settings/public` serves it. `volume` is
    // 'L', capital, and a lowercase 'l' resolves to no adapter at all -- the
    // component then crashes on `adapter.unit` before rendering anything.
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
  }),
}))

import TireList from '../TireList'

const VIN = '1HGCM82633A004352'
const CORNERS = ['FL', 'FR', 'RL', 'RR'] as const

/** A mounted tire whose id encodes its corner, so a move is readable. */
const tireAt = (id: number, position: string) => ({
  id,
  vin: VIN,
  position,
  brand: 'Michelin',
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
})

const FOUR_MOUNTED = [tireAt(1, 'FL'), tireAt(2, 'FR'), tireAt(3, 'RL'), tireAt(4, 'RR')]
/* SPARE counts. Four mounted tires leave the spare slot free, so Add still had
 * somewhere to go and the storage default was never reached -- the first
 * version of the tests below asserted against this list and passed on the old
 * code too. */
const EVERY_SLOT_TAKEN = [...FOUR_MOUNTED, tireAt(5, 'SPARE')]
const CORNER_BY_ID: Record<number, string> = { 1: 'FL', 2: 'FR', 3: 'RL', 4: 'RR' }

/** The four pattern chips, in the order the drawer renders them. */
const PATTERN_KEYS = [
  'tireList.rotatePatterns.forwardCross',
  'tireList.rotatePatterns.rearwardCross',
  'tireList.rotatePatterns.xPattern',
  'tireList.rotatePatterns.frontToBack',
] as const

/** The open drawer. Both Rotate buttons render the same label, so scope. */
const drawer = () => within(screen.getByRole('dialog'))

const setSets = (sets: unknown[]) =>
  useTireSetsMock.mockReturnValue({
    data: { sets, total: sets.length },
    isLoading: false,
    error: null,
  })

const setTires = (tires: unknown[]) =>
  useTiresMock.mockReturnValue({
    data: { tires, total: tires.length },
    isLoading: false,
    error: null,
  })

describe('TireList rotation', () => {
  afterEach(() => vi.restoreAllMocks())

  beforeEach(() => {
    useCreateTireMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useCreateAndMountTireMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useRetireTireMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useRotateTiresMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useDeleteTireMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useCreateTireSetMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useMountTireSetMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useUpdateTireMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    setSets([])
    setTires(FOUR_MOUNTED)
  })

  it.each(PATTERN_KEYS)('%s moves every tire to a distinct corner', (patternKey) => {
    const mutate = vi.fn()
    useRotateTiresMock.mockReturnValue({ mutate, isPending: false })

    render(<TireList vin={VIN} />)
    fireEvent.click(screen.getByText('tireList.rotate'))
    fireEvent.click(drawer().getByText(patternKey))
    fireEvent.click(drawer().getByText('tireList.rotate'))

    const moves = mutate.mock.calls[0][0].moves as { tire_id: number; position: string }[]

    // A permutation, asserted in both directions. A pattern that sent two
    // tires to one corner would be rejected by the request schema with a 422
    // the user cannot act on; one that dropped a corner would silently leave a
    // tire where it was, which reads as a rotation that worked.
    expect(moves).toHaveLength(CORNERS.length)
    expect([...moves.map((m) => m.tire_id)].sort()).toEqual([1, 2, 3, 4])
    expect([...moves.map((m) => m.position)].sort()).toEqual([...CORNERS].sort())

    // And no tire stays put. True of all four standard patterns, and a
    // rotation that leaves a tire on its own corner is not one.
    for (const move of moves) {
      expect(move.position).not.toBe(CORNER_BY_ID[move.tire_id])
    }
  })

  it('sends the pattern the user picked, not the default', () => {
    const mutate = vi.fn()
    useRotateTiresMock.mockReturnValue({ mutate, isPending: false })

    render(<TireList vin={VIN} />)
    fireEvent.click(screen.getByText('tireList.rotate'))
    fireEvent.click(drawer().getByText('tireList.rotatePatterns.frontToBack'))
    fireEvent.change(drawer().getByLabelText('tireList.odometerWithUnit'), {
      target: { value: '48000' },
    })
    fireEvent.click(drawer().getByText('tireList.rotate'))

    // Front-to-back keeps each tire on its own SIDE, which is the whole point
    // of the pattern and the thing that distinguishes it from the other three.
    // Asserted as the exact map rather than as a property, because "every tire
    // stayed on its side" is also true of doing nothing.
    expect(mutate.mock.calls[0][0]).toMatchObject({
      odometer_km: 48000,
      moves: [
        { tire_id: 1, position: 'RL' },
        { tire_id: 2, position: 'RR' },
        { tire_id: 3, position: 'FL' },
        { tire_id: 4, position: 'FR' },
      ],
    })
  })

  it('is refused when a corner is empty', () => {
    // Three mounted, one bare. The server would answer 404 for the missing
    // tire or 409 for a corner held outside the rotation, and neither is
    // something a user can act on from a list that already shows the gap.
    setTires(FOUR_MOUNTED.slice(0, 3))
    render(<TireList vin={VIN} />)

    expect(screen.getByText('tireList.rotate').closest('button')).toBeDisabled()
  })
})

describe('TireList retire', () => {
  afterEach(() => vi.restoreAllMocks())

  beforeEach(() => {
    useCreateTireMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useCreateAndMountTireMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useRetireTireMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useRotateTiresMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useDeleteTireMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useCreateTireSetMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useMountTireSetMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useUpdateTireMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    setSets([])
    setTires(FOUR_MOUNTED)
  })

  it('retires the tire, and does not delete it', () => {
    const retire = vi.fn()
    const remove = vi.fn()
    useRetireTireMock.mockReturnValue({ mutate: retire, isPending: false })
    useDeleteTireMock.mockReturnValue({ mutate: remove, isPending: false })

    render(<TireList vin={VIN} />)
    fireEvent.click(screen.getAllByText('tireList.retire')[0])
    fireEvent.change(drawer().getByLabelText('tireList.odometerWithUnit'), {
      target: { value: '61000' },
    })
    fireEvent.click(drawer().getByText('tireList.retire'))

    expect(retire).toHaveBeenCalledWith(
      { tireId: 1, dismounted_odometer_km: 61000 },
      expect.anything()
    )
    // The distinction the whole endpoint exists for: delete cascades through
    // every reading and every mount period.
    expect(remove).not.toHaveBeenCalled()
  })

  it('reaches a stored tire too', () => {
    // A set can wear out and be replaced without ever going back on.
    setTires([{ ...tireAt(9, 'FL'), position: null }])
    const retire = vi.fn()
    useRetireTireMock.mockReturnValue({ mutate: retire, isPending: false })

    render(<TireList vin={VIN} />)
    fireEvent.click(screen.getByText('tireList.retire'))
    fireEvent.click(drawer().getByText('tireList.retire'))

    expect(retire.mock.calls[0][0].tireId).toBe(9)
  })
})

describe('TireList create into storage', () => {
  afterEach(() => vi.restoreAllMocks())

  beforeEach(() => {
    useCreateTireMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useCreateAndMountTireMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useRetireTireMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useRotateTiresMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useDeleteTireMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useCreateTireSetMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useMountTireSetMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useUpdateTireMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    setSets([])
    setTires(FOUR_MOUNTED)
  })

  it('can still add a tire when every slot is taken', () => {
    // The state a second seasonal set is entered in, and the one where Add was
    // disabled outright -- so this was the single moment a winter set most
    // obviously needed entering and nothing could be entered at all.
    setTires(EVERY_SLOT_TAKEN)
    render(<TireList vin={VIN} />)
    expect(screen.getByText('tireList.add').closest('button')).not.toBeDisabled()
  })

  it('posts to create, not create-and-mount, and carries no position', () => {
    const create = vi.fn()
    const createAndMount = vi.fn()
    useCreateTireMock.mockReturnValue({ mutate: create, isPending: false })
    useCreateAndMountTireMock.mockReturnValue({ mutate: createAndMount, isPending: false })

    render(<TireList vin={VIN} />)
    fireEvent.click(screen.getByText('tireList.add'))
    fireEvent.click(drawer().getByText('tireList.inStorage'))
    fireEvent.change(drawer().getByLabelText('tireList.brand'), {
      target: { value: 'Nokian' },
    })
    fireEvent.click(drawer().getByText('common:save'))

    // `POST /tires` declares extra="forbid", so a `position` key on this
    // payload is a 422 rather than a field the server ignores.
    expect(createAndMount).not.toHaveBeenCalled()
    expect(create).toHaveBeenCalledTimes(1)
    const payload = create.mock.calls[0][0]
    expect(payload).toMatchObject({ vin: VIN, brand: 'Nokian' })
    expect(payload).not.toHaveProperty('position')
  })

  it('opens on storage when there is nowhere left to mount', () => {
    const create = vi.fn()
    const createAndMount = vi.fn()
    useCreateTireMock.mockReturnValue({ mutate: create, isPending: false })
    useCreateAndMountTireMock.mockReturnValue({ mutate: createAndMount, isPending: false })

    // No chip clicked: the default alone has to be storage, because the old
    // fallback selected an OCCUPIED corner that the form then could not submit.
    setTires(EVERY_SLOT_TAKEN)
    render(<TireList vin={VIN} />)
    fireEvent.click(screen.getByText('tireList.add'))
    fireEvent.click(drawer().getByText('common:save'))

    expect(createAndMount).not.toHaveBeenCalled()
    expect(create).toHaveBeenCalledTimes(1)
  })

  it('still mounts when a corner is free and chosen', () => {
    // The pair to the test above: storage must not become the default for
    // everyone, only the default when there is nowhere to mount.
    setTires(FOUR_MOUNTED.slice(0, 3))
    const create = vi.fn()
    const createAndMount = vi.fn()
    useCreateTireMock.mockReturnValue({ mutate: create, isPending: false })
    useCreateAndMountTireMock.mockReturnValue({ mutate: createAndMount, isPending: false })

    render(<TireList vin={VIN} />)
    fireEvent.click(screen.getByText('tireList.add'))
    fireEvent.click(drawer().getByText('common:save'))

    expect(create).not.toHaveBeenCalled()
    expect(createAndMount.mock.calls[0][0].position).toBe('RR')
  })
})

describe('TireList sets', () => {
  const WINTER = { id: 7, vin: VIN, name: 'Winter studded', notes: null, created_at: '2026-01-01T00:00:00', tire_ids: [1, 2], mounted_count: 0 }
  const EMPTY_SET = { id: 8, vin: VIN, name: 'Spares', notes: null, created_at: '2026-01-01T00:00:00', tire_ids: [], mounted_count: 0 }

  afterEach(() => vi.restoreAllMocks())

  beforeEach(() => {
    useCreateTireMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useCreateAndMountTireMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useRetireTireMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useRotateTiresMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useDeleteTireMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useCreateTireSetMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useMountTireSetMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useUpdateTireMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    setSets([])
    setTires(FOUR_MOUNTED)
  })

  it('creates a set from the name the user typed', () => {
    const mutate = vi.fn()
    useCreateTireSetMock.mockReturnValue({ mutate, isPending: false })

    render(<TireList vin={VIN} />)
    fireEvent.click(screen.getByText('tireList.sets'))
    fireEvent.change(drawer().getByLabelText('tireList.setName'), {
      target: { value: '  Winter studded  ' },
    })
    fireEvent.click(drawer().getByText('tireList.setAdd'))

    // Trimmed: a trailing space is invisible in the list and makes two sets
    // that read identically.
    expect(mutate).toHaveBeenCalledWith({ name: 'Winter studded' }, expect.anything())
  })

  it('fits a set with the odometer, and sends no positions', () => {
    const mutate = vi.fn()
    useMountTireSetMock.mockReturnValue({ mutate, isPending: false })
    setSets([WINTER])

    render(<TireList vin={VIN} />)
    fireEvent.click(screen.getByText('tireList.sets'))
    fireEvent.click(drawer().getByText('tireList.setFit'))
    fireEvent.change(drawer().getByLabelText('tireList.odometerWithUnit'), {
      target: { value: '52000' },
    })
    // The expanded form's confirm, not the row control that opened it.
    fireEvent.click(drawer().getAllByText('tireList.setFit')[1])

    // No `moves`, no positions: the server reads each tire's own history for
    // the corner it was last on. A client that guessed would have to reproduce
    // that lookup and could disagree with it.
    expect(mutate).toHaveBeenCalledWith(
      { setId: 7, odometer_km: 52000 },
      expect.anything()
    )
  })

  it('does not offer to fit an empty set', () => {
    setSets([EMPTY_SET])
    render(<TireList vin={VIN} />)
    fireEvent.click(screen.getByText('tireList.sets'))

    // The server answers 409 for this, and the message tells the user to go
    // and put tires in the set -- which they cannot do from here.
    expect(drawer().getByText('tireList.setFit').closest('button')).toBeDisabled()
  })

  it('files a tire into a set through the edit drawer', () => {
    const mutate = vi.fn()
    useUpdateTireMock.mockReturnValue({ mutate, isPending: false })
    setSets([WINTER])

    render(<TireList vin={VIN} />)
    fireEvent.click(screen.getAllByLabelText('tireList.edit')[0])
    fireEvent.click(drawer().getByText('Winter studded'))
    fireEvent.click(drawer().getByText('common:save'))

    expect(mutate.mock.calls[0][0]).toMatchObject({ tireId: 1, set_id: 7 })
  })

  it('does not offer the set picker while adding', () => {
    // `POST /tires` declares extra="forbid", so a `set_id` on a create is a
    // 422. A control that cannot be used yet reads as broken.
    setSets([WINTER])
    render(<TireList vin={VIN} />)
    fireEvent.click(screen.getByText('tireList.add'))

    expect(drawer().queryByText('tireList.setLabel')).toBeNull()
  })

  it('groups stored tires under their set name', () => {
    setSets([WINTER])
    setTires([
      { ...tireAt(1, 'FL'), position: null, set_id: 7, brand: 'Nokian' },
      { ...tireAt(2, 'FR'), position: null, set_id: null, brand: 'Loose' },
    ])

    render(<TireList vin={VIN} />)

    // Both headings, because two groups exist. One flat list is what makes a
    // second seasonal set unreadable.
    expect(screen.getByText('Winter studded')).toBeInTheDocument()
    expect(screen.getByText('tireList.setUngrouped')).toBeInTheDocument()
  })

  it('does not label the group when there is only one', () => {
    // A single-set owner sees exactly what they saw before sets existed.
    setSets([WINTER])
    setTires([{ ...tireAt(1, 'FL'), position: null, set_id: 7, brand: 'Nokian' }])

    render(<TireList vin={VIN} />)

    expect(screen.queryByText('Winter studded')).toBeNull()
  })
})
