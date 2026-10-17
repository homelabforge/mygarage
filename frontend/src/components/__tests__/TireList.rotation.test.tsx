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
const useMountTireMock = vi.fn()
const useDismountTireMock = vi.fn()
const useRestoreTireMock = vi.fn()
const noop = () => ({ mutate: vi.fn(), isPending: false })

// Every mutation gets its OWN mock here, unlike TireList.test.tsx which aliases
// several onto one. The distinction is the whole subject: retire must not be
// delete, and create-into-storage must not be create-and-mount.
vi.mock('../../hooks/queries/useTires', () => ({
  useTires: () => useTiresMock(),
  useCreateTire: () => useCreateTireMock(),
  useCreateAndMountTire: () => useCreateAndMountTireMock(),
  useUpdateTire: () => useUpdateTireMock(),
  useMountTire: () => useMountTireMock(),
  useDismountTire: () => useDismountTireMock(),
  useRestoreTire: () => useRestoreTireMock(),
  useRetireTire: () => useRetireTireMock(),
  useRotateTires: () => useRotateTiresMock(),
  useAddTireReading: () => noop(),
  useDeleteTire: () => useDeleteTireMock(),
  useDeleteTireReading: () => ({ mutate: vi.fn(), isPending: false }),
  useTireSets: () => useTireSetsMock(),
  useCreateTireSet: () => useCreateTireSetMock(),
  useUpdateTireSet: () => noop(),
  useDeleteTireSet: () => noop(),
  useMountTireSet: () => useMountTireSetMock(),
}))

vi.mock('../../hooks/queries/useOdometerRecords', () => ({
  useNearestOdometer: () => ({ data: undefined, isSuccess: false }),
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
import { formatDateForInput } from '../../utils/dateUtils'

const VIN = '1HGCM82633A004352'
const CORNERS = ['FL', 'FR', 'RL', 'RR'] as const

/** A mounted tire whose id encodes its corner, so a move is readable. */
const tireAt = (id: number, position: string | null) => ({
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

/** The open drawer. Both Rotate buttons render the same label, so scope.
 *
 * The LAST dialog in the DOM, not the only one: `Drawer` keeps a closing
 * panel mounted for the tail of its exit transition (so the slide-out
 * actually plays), so a test that moves from one drawer straight into a
 * DIFFERENT one -- as the dates-and-storage-location suite does, retire then
 * rotate then sets -- briefly has the outgoing panel and the incoming one
 * both in the DOM. The most recently opened one is always the one still
 * being interacted with. */
const drawer = () => {
  const dialogs = screen.getAllByRole('dialog')
  return within(dialogs[dialogs.length - 1])
}

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
    useMountTireMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useDismountTireMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useRestoreTireMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
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

  it('after a rotation offers to log the brakes while the wheels are off (#202)', () => {
    const mutate = vi.fn((_payload: unknown, opts: { onSuccess?: () => void }) => opts.onSuccess?.())
    useRotateTiresMock.mockReturnValue({ mutate, isPending: false })
    const onLogBrakes = vi.fn()

    render(<TireList vin={VIN} onLogBrakes={onLogBrakes} />)
    expect(screen.queryByText('tireList.brakesPrompt')).toBeNull()
    fireEvent.click(screen.getByText('tireList.rotate'))
    fireEvent.click(drawer().getByText('tireList.rotate'))

    fireEvent.click(screen.getByRole('button', { name: 'tireList.brakesPromptAction' }))
    expect(onLogBrakes).toHaveBeenCalledTimes(1)
    fireEvent.click(screen.getByRole('button', { name: 'tireList.brakesPromptDismiss' }))
    expect(screen.queryByText('tireList.brakesPrompt')).toBeNull()
  })

  it('has no brake prompt where there is no Brakes tab to go to', () => {
    const mutate = vi.fn((_payload: unknown, opts: { onSuccess?: () => void }) => opts.onSuccess?.())
    useRotateTiresMock.mockReturnValue({ mutate, isPending: false })

    render(<TireList vin={VIN} />)
    fireEvent.click(screen.getByText('tireList.rotate'))
    fireEvent.click(drawer().getByText('tireList.rotate'))
    expect(screen.queryByText('tireList.brakesPrompt')).toBeNull()
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
    useMountTireMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useDismountTireMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useRestoreTireMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
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

    // toMatchObject, not toHaveBeenCalledWith: the payload also carries
    // dismounted_on now (v3.4.0), asserted by its own test below.
    expect(retire.mock.calls[0][0]).toMatchObject({ tireId: 1, dismounted_odometer_km: 61000 })
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
    useMountTireMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useDismountTireMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useRestoreTireMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
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
    expect(payload).not.toHaveProperty('mounted_on')
    expect(payload).not.toHaveProperty('mounted_odometer_km')
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
    const payload = createAndMount.mock.calls[0][0]
    // The v3.3.0 defect: the corner branch sent no mount fields at all, so
    // every tire added here had an unbounded period.
    expect(payload.mounted_on).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    expect(payload).toHaveProperty('mounted_odometer_km')
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
    useMountTireMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useDismountTireMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useRestoreTireMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
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
    // that lookup and could disagree with it. toMatchObject, not
    // toHaveBeenCalledWith: the payload also carries mounted_on now (v3.4.0),
    // asserted by its own test below.
    expect(mutate.mock.calls[0][0]).toMatchObject({ setId: 7, odometer_km: 52000 })
    expect(mutate.mock.calls[0][0]).not.toHaveProperty('moves')
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

describe('TireList dates and storage location', () => {
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
    useMountTireMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useDismountTireMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useRestoreTireMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    setSets([])
    setTires(FOUR_MOUNTED)
  })

  const DATE = /^\d{4}-\d{2}-\d{2}$/

  it('the corner branch of Add Tire sends the typed odometer and a backdated date', () => {
    const createAndMount = vi.fn()
    useCreateAndMountTireMock.mockReturnValue({ mutate: createAndMount, isPending: false })
    setTires(FOUR_MOUNTED.slice(0, 3))
    render(<TireList vin={VIN} />)
    fireEvent.click(screen.getByText('tireList.add'))
    fireEvent.change(drawer().getByLabelText('tireList.mountedOn'), { target: { value: '2026-04-10' } })
    fireEvent.change(document.getElementById('tire-mount-odometer') as HTMLInputElement, { target: { value: '152159' } })
    fireEvent.click(drawer().getByText('common:save'))
    expect(createAndMount.mock.calls[0][0]).toMatchObject({ mounted_on: '2026-04-10', mounted_odometer_km: 152159 })
  })

  it('the storage branch sends a storage location and hides the mount fields', () => {
    const create = vi.fn()
    useCreateTireMock.mockReturnValue({ mutate: create, isPending: false })
    render(<TireList vin={VIN} />)
    fireEvent.click(screen.getByText('tireList.add'))
    fireEvent.click(drawer().getByText('tireList.inStorage'))
    expect(document.getElementById('tire-mount-odometer')).toBeNull()
    fireEvent.change(drawer().getByLabelText('tireList.storageLocation'), { target: { value: 'Garage shelf B' } })
    fireEvent.click(drawer().getByText('common:save'))
    expect(create.mock.calls[0][0]).toMatchObject({ storage_location: 'Garage shelf B' })
  })

  it('a location typed on In storage is not sent once the tire goes to a corner', () => {
    // The corner branch does not render the location input, so whatever was
    // typed before switching would be saved where this form no longer shows it.
    const createAndMount = vi.fn()
    useCreateAndMountTireMock.mockReturnValue({ mutate: createAndMount, isPending: false })
    setTires(FOUR_MOUNTED.slice(0, 3))
    render(<TireList vin={VIN} />)
    fireEvent.click(screen.getByText('tireList.add'))
    fireEvent.click(drawer().getByText('tireList.inStorage'))
    fireEvent.change(drawer().getByLabelText('tireList.storageLocation'), { target: { value: 'Garage shelf B' } })
    fireEvent.click(drawer().getByText('RR'))
    expect(drawer().queryByLabelText('tireList.storageLocation')).toBeNull()
    fireEvent.click(drawer().getByText('common:save'))
    expect(createAndMount.mock.calls[0][0].position).toBe('RR')
    expect(createAndMount.mock.calls[0][0]).not.toHaveProperty('storage_location')
  })

  it('edit still sends the storage location it renders', () => {
    const update = vi.fn()
    useUpdateTireMock.mockReturnValue({ mutate: update, isPending: false })
    render(<TireList vin={VIN} />)
    fireEvent.click(screen.getAllByLabelText('tireList.edit')[0])
    fireEvent.change(drawer().getByLabelText('tireList.storageLocation'), { target: { value: ' Loft ' } })
    fireEvent.click(drawer().getByText('common:save'))
    expect(update.mock.calls[0][0]).toMatchObject({ tireId: 1, storage_location: 'Loft' })
  })

  describe('each event dialog opens fresh', () => {
    const TODAY = formatDateForInput()
    const STORED = [
      { ...tireAt(9, null), brand: 'First' },
      { ...tireAt(10, null), brand: 'Second' },
    ]
    const MOUNTED = [
      { ...tireAt(1, 'FL'), brand: 'First' },
      { ...tireAt(2, 'FR'), brand: 'Second' },
    ]
    const cardOf = (brand: string): ReturnType<typeof within> =>
      within(screen.getByText(brand).closest('.rounded-card') as HTMLElement)

    /* Type a date and an odometer, cancel, then open the same dialog for the
     * other tire. Before, both values survived the cancel. */
    const dirtyCancelReopen = (open: (brand: string) => void, dateLabel: string): void => {
      open('First')
      fireEvent.change(drawer().getByLabelText(dateLabel), { target: { value: '2026-01-05' } })
      fireEvent.change(drawer().getByLabelText('tireList.odometerWithUnit'), {
        target: { value: '12345' },
      })
      fireEvent.click(drawer().getByText('common:cancel'))
      open('Second')
      expect(drawer().getByLabelText(dateLabel)).toHaveValue(TODAY)
      expect(drawer().getByLabelText('tireList.odometerWithUnit')).toHaveValue(null)
    }

    it('mount', () => {
      setTires(STORED)
      render(<TireList vin={VIN} />)
      dirtyCancelReopen((brand) => fireEvent.click(cardOf(brand).getByText('tireList.mount')), 'tireList.mountedOn')
    })

    it('dismount, keeping the storage location seeded from the tire', () => {
      setTires([MOUNTED[0], { ...MOUNTED[1], storage_location: 'Shed' }])
      render(<TireList vin={VIN} />)
      dirtyCancelReopen((brand) => fireEvent.click(cardOf(brand).getByText('tireList.dismount')), 'tireList.eventDate')
      expect(drawer().getByLabelText('tireList.storageLocation')).toHaveValue('Shed')
    })

    it('retire', () => {
      setTires(MOUNTED)
      render(<TireList vin={VIN} />)
      dirtyCancelReopen((brand) => fireEvent.click(cardOf(brand).getByText('tireList.retire')), 'tireList.eventDate')
    })

    it('rotate', () => {
      setTires(FOUR_MOUNTED)
      render(<TireList vin={VIN} />)
      dirtyCancelReopen(() => fireEvent.click(screen.getAllByText('tireList.rotate')[0]), 'tireList.eventDate')
    })
  })

  it('mount sends its date', () => {
    const mutate = vi.fn()
    useMountTireMock.mockReturnValue({ mutate, isPending: false })
    setTires([{ ...tireAt(9, 'FL'), position: null }])
    render(<TireList vin={VIN} />)
    fireEvent.click(screen.getByText('tireList.mount'))
    fireEvent.click(drawer().getByText('FR'))
    fireEvent.click(within(screen.getByRole('dialog')).getByText('tireList.mount'))
    expect(mutate.mock.calls[0][0].mounted_on).toMatch(DATE)
  })

  it('dismount sends its date and the storage location', () => {
    const mutate = vi.fn()
    useDismountTireMock.mockReturnValue({ mutate, isPending: false })
    render(<TireList vin={VIN} />)
    fireEvent.click(screen.getAllByText('tireList.dismount')[0])
    fireEvent.change(drawer().getByLabelText('tireList.storageLocation'), { target: { value: 'Shed' } })
    fireEvent.click(drawer().getByText('tireList.dismount'))
    expect(mutate.mock.calls[0][0]).toMatchObject({ storage_location: 'Shed' })
    expect(mutate.mock.calls[0][0].dismounted_on).toMatch(DATE)
  })

  it('dismount seeds the storage location from the tire, and a blank clears it', () => {
    const mutate = vi.fn()
    useDismountTireMock.mockReturnValue({ mutate, isPending: false })
    setTires([{ ...tireAt(1, 'FL'), storage_location: 'Shed' }])
    render(<TireList vin={VIN} />)
    fireEvent.click(screen.getByText('tireList.dismount'))
    expect(drawer().getByLabelText('tireList.storageLocation')).toHaveValue('Shed')
    fireEvent.change(drawer().getByLabelText('tireList.storageLocation'), { target: { value: '' } })
    fireEvent.click(drawer().getByText('tireList.dismount'))
    expect(mutate.mock.calls[0][0].storage_location).toBe('')
  })

  it('retire, rotate and set fit send their dates', () => {
    // Each mock resolves onSuccess, same as a real successful mutation: three
    // SEPARATE Drawer instances are opened in sequence here, and each one
    // only closes its own state on success, so the next one would otherwise
    // open on top of a still-mounted predecessor.
    const retire = vi.fn((_payload, handlers) => handlers.onSuccess())
    const rotate = vi.fn((_payload, handlers) => handlers.onSuccess())
    const fit = vi.fn((_payload, handlers) => handlers.onSuccess())
    useRetireTireMock.mockReturnValue({ mutate: retire, isPending: false })
    useRotateTiresMock.mockReturnValue({ mutate: rotate, isPending: false })
    useMountTireSetMock.mockReturnValue({ mutate: fit, isPending: false })
    setSets([{ id: 7, vin: VIN, name: 'Winter', notes: null, created_at: '2026-01-01T00:00:00', tire_ids: [1], mounted_count: 0 }])
    render(<TireList vin={VIN} />)

    fireEvent.click(screen.getAllByText('tireList.retire')[0])
    fireEvent.click(drawer().getByText('tireList.retire'))
    expect(retire.mock.calls[0][0].dismounted_on).toMatch(DATE)

    fireEvent.click(screen.getByText('tireList.rotate'))
    fireEvent.click(drawer().getByText('tireList.rotate'))
    expect(rotate.mock.calls[0][0].rotated_on).toMatch(DATE)

    fireEvent.click(screen.getByText('tireList.sets'))
    fireEvent.click(drawer().getByText('tireList.setFit'))
    fireEvent.click(drawer().getAllByText('tireList.setFit')[1])
    expect(fit.mock.calls[0][0].mounted_on).toMatch(DATE)
  })
})

describe('TireList retired tires', () => {
  afterEach(() => vi.restoreAllMocks())
  const RETIRED = { ...tireAt(6, null), position: null, retired_on: '2026-05-01' }

  beforeEach(() => {
    useCreateTireMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useCreateAndMountTireMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useRetireTireMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useRotateTiresMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useDeleteTireMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useCreateTireSetMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useMountTireSetMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useUpdateTireMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useMountTireMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useDismountTireMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useRestoreTireMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    setSets([])
    setTires([...FOUR_MOUNTED, RETIRED])
  })

  it('hides retired tires until asked, then shows them with Restore only', () => {
    const restore = vi.fn()
    useRestoreTireMock.mockReturnValue({ mutate: restore, isPending: false })
    render(<TireList vin={VIN} />)
    expect(screen.queryByText('tireList.retiredHeading')).toBeNull()
    expect(screen.queryByText('tireList.restore')).toBeNull()

    fireEvent.click(screen.getByLabelText('tireList.showRetired'))
    expect(screen.getByText('tireList.retiredHeading')).toBeInTheDocument()
    const card = screen.getByText('tireList.restore').closest('.rounded-card') as HTMLElement
    expect(within(card).getByText('tireList.retiredOn')).toBeInTheDocument()
    expect(within(card).queryByText('tireList.mount')).toBeNull()
    expect(within(card).queryByText('tireList.retire')).toBeNull()
    expect(within(card).queryByLabelText('tireList.edit')).toBeNull()

    fireEvent.click(within(card).getByText('tireList.restore'))
    expect(restore).toHaveBeenCalledWith(6, expect.anything())
  })
})
