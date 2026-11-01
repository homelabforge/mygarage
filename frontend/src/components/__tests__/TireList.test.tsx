import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'

// Mock the query hooks so this stays a unit test - no QueryClient/api wiring.
const useTiresMock = vi.fn()
const useUpsertTireMock = vi.fn()
const useAddTireReadingMock = vi.fn()
const useDeleteTireMock = vi.fn()

// v3.3.0 split the single upsert into create-and-mount plus update, and added
// mount/dismount. The old `useUpsertTire` name is kept for the mock variable
// because every assertion below is about the payload a save produces, and that
// payload is now create-and-mount's.
vi.mock('../../hooks/queries/useTires', () => ({
  useTires: () => useTiresMock(),
  useCreateAndMountTire: () => useUpsertTireMock(),
  useCreateTire: () => useUpsertTireMock(),
  useUpdateTire: () => useUpsertTireMock(),
  useMountTire: () => useUpsertTireMock(),
  useDismountTire: () => useUpsertTireMock(),
  useRestoreTire: () => useUpsertTireMock(),
  useRetireTire: () => useUpsertTireMock(),
  useRotateTires: () => useUpsertTireMock(),
  useAddTireReading: () => useAddTireReadingMock(),
  useDeleteTire: () => useDeleteTireMock(),
  useDeleteTireReading: () => ({ mutate: vi.fn(), isPending: false }),
  // Sets are not this file's subject; it just has to render past them.
  useTireSets: () => ({ data: { sets: [], total: 0 }, isLoading: false, error: null }),
  useCreateTireSet: () => useUpsertTireMock(),
  useUpdateTireSet: () => useUpsertTireMock(),
  useDeleteTireSet: () => useUpsertTireMock(),
  useMountTireSet: () => useUpsertTireMock(),
}))

vi.mock('../../hooks/queries/useOdometerRecords', () => ({
  useNearestOdometer: () => ({ data: undefined, isSuccess: false }),
}))

vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}))

// useUnitPreference calls useAuth, which throws outside an AuthProvider, and the
// shared renderer does not supply one. Imperial is what exercises conversion.
//
// The resolved set is written out here rather than imported from the factories,
// so this file states the units it is asserting against. `useUnitFormat` is NOT
// mocked: the conversions below are the real adapters running.
vi.mock('../../hooks/useUnitPreference', () => {
  // UnitSession reads the account half too; same answer, nothing to pin here.
  const unitPreference = () => ({
    system: 'imperial',
    showBoth: false,
    gallonStandard: 'us',
    units: {
      distance: 'mi',
      speed: 'mph',
      length: 'ft',
      volume: 'gal_us',
      consumption: 'mpg_us',
      pressure: 'psi',
      temperature: 'f',
      mass: 'lb',
      torque: 'lbft',
      tread: 'in32',
      secondary_gallon: 'us',
    },
  })
  return {
    useUnitPreference: unitPreference,
    useAccountUnitPreference: unitPreference,
  }
})

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

    // No `position` in an edit payload since v3.3.0. Editing a tire's
    // metadata does not move it: where a tire sits changes through
    // mount/dismount, and `position` is not a writable field at all -- the
    // backend rejects a payload carrying one with a 422.
    const payload = mutate.mock.calls[0][0]
    expect(payload).toMatchObject({
      tireId: 1,
      brand: 'Michelin',
      model_name: 'Pilot Sport 4',
      size: '225/45R17',
      dot_code: '2324',
    })
    expect(payload).not.toHaveProperty('position')
  })

  it('posts a blank reading odometer as null', () => {
    // Replaces a test that asserted `tireList.odometerMi` present and
    // `tireList.odometerKm` absent. One interpolated key plus a mock `t` that
    // returns the key made both assertions unit-independent, so the name
    // claimed a property the body no longer exercised. The imperial
    // discriminator is the conversion test below; the metric one is its pair.
    const mutate = vi.fn()
    useAddTireReadingMock.mockReturnValue({ mutate, isPending: false })

    render(<TireList vin="1HGCM82633A004352" />)
    fireEvent.click(screen.getByText('tireList.addReading'))

    const odo = screen.getByLabelText('tireList.odometerWithUnit') as HTMLInputElement
    expect(odo.value).toBe('')

    // Tread is seeded from the tire, so this saves without touching anything.
    fireEvent.click(screen.getByText('common:save'))

    // `0` would be posted if a blank field converted instead of clearing, and
    // `tire_service.py` differences consecutive readings' odometers for the
    // wear projection, so a zero poisons it rather than being ignored.
    expect(mutate.mock.calls[0][0].odometer_km).toBeNull()
  })

  it('submits canonical km when the user works in miles', () => {
    const mutate = vi.fn()
    useAddTireReadingMock.mockReturnValue({ mutate, isPending: false })

    render(<TireList vin="1HGCM82633A004352" />)
    fireEvent.click(screen.getByText('tireList.addReading'))
    fireEvent.change(screen.getByLabelText('tireList.odometerWithUnit'), {
      target: { value: '100' },
    })
    fireEvent.click(screen.getByText('common:save'))

    // 100 mi x 1.609344 = 160.9344 km. The adapter does not round a canonical
    // write to two decimals the way `UnitConverter.milesToKm` did; it keeps the
    // exact conversion, as `UnitConverter.toCanonicalMetricString` already does
    // for every other form. The column is Numeric(10,2), so the server stores
    // 160.93 either way.
    expect(mutate.mock.calls[0][0].odometer_km).toBe(160.9344)
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

    // 240 kPa / 6.894757... = 34.809..., and PSI renders at one decimal.
    const input = screen.getByLabelText('tireList.pressureWithUnit') as HTMLInputElement
    expect(input.value).toBe('34.8')
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
  /**
   * L4: tread is an ENTRY and STORAGE boundary, not a display bug.
   *
   * Storage is millimetres; an imperial user reads and types thirty-seconds of
   * an inch (1/32 in = 0.79375 mm). Converting only the label would make a user
   * who types `9` store 9 mm where 7.14375 belongs, which is a corruption
   * introduced BY the fix, so each test below asserts the displayed unit first
   * and the stored millimetres second. A test that only asserted the stored
   * value would pass just as well with no conversion at all.
   */
  describe('tread conversion (L4)', () => {
    it('stores the millimetres a typed thirty-second means, not the number typed', () => {
      const mutate = vi.fn()
      useUpsertTireMock.mockReturnValue({ mutate, isPending: false })

      render(<TireList vin="1HGCM82633A004352" />)
      fireEvent.click(screen.getByLabelText('tireList.edit'))

      // 7.50 mm / 0.79375 = 9.4488..., and in32 renders at 0 decimals.
      const tread = screen.getByLabelText('tireList.treadWithUnit') as HTMLInputElement
      expect(tread.value).toBe('9')

      fireEvent.change(tread, { target: { value: '10' } })
      fireEvent.click(screen.getByText('common:save'))

      // 10/32 in x 0.79375 = 7.9375 mm
      expect(mutate.mock.calls[0][0].tread_depth_mm).toBe(7.9375)
    })

    it('stores the canonical 2.0 mm default when an imperial Add form is untouched', () => {
      const mutate = vi.fn()
      useUpsertTireMock.mockReturnValue({ mutate, isPending: false })

      render(<TireList vin="1HGCM82633A004352" />)
      fireEvent.click(screen.getByText('tireList.add'))

      // 2.0 mm / 0.79375 = 2.5196..., which renders as 3. Reading that back as
      // 3/32 in would store 2.38125 mm, and reading the raw default as
      // thirty-seconds would store 1.5875 mm; the user touched neither.
      const minTread = screen.getByLabelText('tireList.minTreadWithUnit') as HTMLInputElement
      expect(minTread.value).toBe('3')

      fireEvent.click(screen.getByText('common:save'))

      expect(mutate.mock.calls[0][0].min_tread_mm).toBe(2)
      expect(mutate.mock.calls[0][0].tread_depth_mm).toBeNull()
    })

    it('leaves every unit-bearing field as stored when an Edit form is untouched', () => {
      const mutate = vi.fn()
      useUpsertTireMock.mockReturnValue({ mutate, isPending: false })

      render(<TireList vin="1HGCM82633A004352" />)
      fireEvent.click(screen.getByLabelText('tireList.edit'))

      // Conversion is on: 7.50 mm is 9/32, 3.00 mm is 4/32, 240 kPa is 34.8 PSI.
      expect((screen.getByLabelText('tireList.treadWithUnit') as HTMLInputElement).value).toBe('9')
      expect(
        (screen.getByLabelText('tireList.minTreadWithUnit') as HTMLInputElement).value
      ).toBe('4')
      expect(
        (screen.getByLabelText('tireList.pressureWithUnit') as HTMLInputElement).value
      ).toBe('34.8')

      fireEvent.click(screen.getByText('common:save'))

      // Re-converting the displayed values would store 7.14375, 3.175 and
      // 239.937648 for a save the user made no edit in.
      const payload = mutate.mock.calls[0][0]
      expect(payload.tread_depth_mm).toBe(7.5)
      expect(payload.min_tread_mm).toBe(3)
      expect(payload.pressure_kpa).toBe(240)
    })

    it('preserves the parent tread when only pressure changes on a Log Reading', () => {
      const mutate = vi.fn()
      useAddTireReadingMock.mockReturnValue({ mutate, isPending: false })

      render(<TireList vin="1HGCM82633A004352" />)
      fireEvent.click(screen.getByText('tireList.addReading'))

      // The reading drawer seeds tread from the tire, in the user's unit.
      expect((screen.getByLabelText('tireList.treadWithUnit') as HTMLInputElement).value).toBe('9')

      fireEvent.change(screen.getByLabelText('tireList.pressureWithUnit'), {
        target: { value: '36' },
      })
      fireEvent.click(screen.getByText('common:save'))

      const payload = mutate.mock.calls[0][0]
      // `tire_service.py` overwrites the parent tire's tread from the newest
      // reading, so a re-converted 7.14375 here silently rewrites a tread the
      // user never touched. This is the reading path's own seed and submit,
      // separate from Add and Edit, which is how it was missed.
      expect(payload.tread_depth_mm).toBe(7.5)
      // 36 PSI x 6.894757293168361 = 248.211262554 kPa, the field that WAS edited.
      expect(payload.pressure_kpa).toBe(248.211262554)
    })

    it('reads the card tread in the same unit the form accepts', () => {
      render(<TireList vin="1HGCM82633A004352" />)

      // Binding decision D2: one unit for entry and display. The card used to
      // print the raw millimetres under a hardcoded "mm".
      expect(screen.getByText('9/32 in')).toBeInTheDocument()
      expect(screen.queryByText('7.50 mm')).not.toBeInTheDocument()
    })

    it('falls back to the canonical 2.0 mm threshold when min tread is cleared', () => {
      const mutate = vi.fn()
      useUpsertTireMock.mockReturnValue({ mutate, isPending: false })

      render(<TireList vin="1HGCM82633A004352" />)
      fireEvent.click(screen.getByLabelText('tireList.edit'))

      // 3.00 mm / 0.79375 = 3.7795..., which renders as 4.
      const minTread = screen.getByLabelText('tireList.minTreadWithUnit') as HTMLInputElement
      expect(minTread.value).toBe('4')

      fireEvent.change(minTread, { target: { value: '' } })
      fireEvent.click(screen.getByText('common:save'))

      // The column is not nullable in practice and the API default is 2.0 mm,
      // so an emptied field means "use the default", in millimetres, not "use
      // 2 thirty-seconds".
      expect(mutate.mock.calls[0][0].min_tread_mm).toBe(2)
    })

    it('refuses a reading with neither tread nor pressure, then saves the converted tread', () => {
      const mutate = vi.fn()
      useAddTireReadingMock.mockReturnValue({ mutate, isPending: false })

      render(<TireList vin="1HGCM82633A004352" />)
      fireEvent.click(screen.getByText('tireList.addReading'))
      const tread = screen.getByLabelText('tireList.treadWithUnit')

      // BOTH have to be cleared to reach the guard now: the drawer seeds tread
      // and pressure from the tire, so clearing tread alone leaves a pressure
      // behind and the reading is a legitimate pressure-only one.
      fireEvent.change(tread, { target: { value: '' } })
      fireEvent.change(screen.getByLabelText('tireList.pressureWithUnit'), {
        target: { value: '' },
      })
      fireEvent.click(screen.getByText('common:save'))
      // On its own this would be true before the click too, so the save below
      // is what makes the refusal mean anything.
      expect(mutate).not.toHaveBeenCalled()

      fireEvent.change(tread, { target: { value: '12' } })
      fireEvent.click(screen.getByText('common:save'))

      expect(mutate).toHaveBeenCalledTimes(1)
      // 12/32 in x 0.79375 = 9.525 mm
      expect(mutate.mock.calls[0][0].tread_depth_mm).toBe(9.525)
      expect(mutate.mock.calls[0][0].pressure_kpa).toBeNull()
    })

    it('saves a pressure-only reading, and an odometer alone does not qualify (#152)', () => {
      const mutate = vi.fn()
      useAddTireReadingMock.mockReturnValue({ mutate, isPending: false })

      render(<TireList vin="1HGCM82633A004352" />)
      fireEvent.click(screen.getByText('tireList.addReading'))
      fireEvent.change(screen.getByLabelText('tireList.treadWithUnit'), { target: { value: '' } })
      const pressure = screen.getByLabelText('tireList.pressureWithUnit')
      fireEvent.change(pressure, { target: { value: '' } })

      // An odometer is context for the wear projection, not an observation of
      // the tire, so it must not satisfy the at-least-one rule on its own.
      fireEvent.change(screen.getByLabelText('tireList.odometerWithUnit'), {
        target: { value: '100' },
      })
      fireEvent.click(screen.getByText('common:save'))
      expect(mutate).not.toHaveBeenCalled()

      // The #152 case: a slow leak, no tread gauge. Refused outright before
      // this change, which is what makes the assertions below fail against it.
      fireEvent.change(pressure, { target: { value: '36' } })
      fireEvent.click(screen.getByText('common:save'))

      expect(mutate).toHaveBeenCalledTimes(1)
      const payload = mutate.mock.calls[0][0]
      // Null, not omitted: `tread_depth_mm` is optional on the wire, and a
      // missing key would leave the reader unable to tell "not measured" from
      // "the client forgot the field".
      expect(payload).toHaveProperty('tread_depth_mm', null)
      // 36 PSI x 6.894757293168361 = 248.211262554 kPa
      expect(payload.pressure_kpa).toBe(248.211262554)
      // 100 mi x 1.609344 = 160.9344 km, carried through as context.
      expect(payload.odometer_km).toBe(160.9344)
    })

    it('takes the tread and pressure as typed text, with no native step to trip', () => {
      render(<TireList vin="1HGCM82633A004352" />)
      fireEvent.click(screen.getByLabelText('tireList.edit'))

      // G1b-21: a native number box refuses a decimal off its step and reads a comma as blank.
      for (const label of ['tireList.treadWithUnit', 'tireList.minTreadWithUnit', 'tireList.pressureWithUnit']) {
        const box = screen.getByLabelText(label)
        expect(box).toHaveAttribute('type', 'text')
        expect(box).not.toHaveAttribute('step')
      }
    })

    /** Seeded as 11 and 2: the 32nds a gauge's 0.346 and 0.0625 in round to. */
    const gauged = (): void => {
      useTiresMock.mockReturnValue({
        data: { tires: [{ ...STORED_FL_TIRE, tread_depth_mm: '8.40', min_tread_mm: '1.60' }], total: 1 },
        isLoading: false,
        error: null,
      })
    }

    it.each([false, true])(
      'reads a gauge decimal typed into Log Reading as inches (blur: %s)',
      (blur) => {
        gauged()
        const mutate = vi.fn()
        useAddTireReadingMock.mockReturnValue({ mutate, isPending: false })

        render(<TireList vin="1HGCM82633A004352" />)
        fireEvent.click(screen.getByText('tireList.addReading'))
        const tread = screen.getByLabelText('tireList.treadWithUnit') as HTMLInputElement
        expect(tread.value).toBe('11')
        fireEvent.change(tread, { target: { value: '.346' } })
        if (blur) fireEvent.blur(tread)
        fireEvent.click(screen.getByText('common:save'))

        // 0.346 in is 11/32 in, 8.73125 mm. Read as 32nds it was 0.27 mm, a
        // healthy tire stored as bald; read against the seeded 11 it was the old 8.40.
        expect(mutate.mock.calls[0][0].tread_depth_mm).toBe(8.73125)
      }
    )

    it.each([false, true])(
      'reads gauge decimals in the tire form as inches, tread and minimum both (blur: %s)',
      (blur) => {
        gauged()
        const mutate = vi.fn()
        useUpsertTireMock.mockReturnValue({ mutate, isPending: false })

        render(<TireList vin="1HGCM82633A004352" />)
        fireEvent.click(screen.getByLabelText('tireList.edit'))
        const tread = screen.getByLabelText('tireList.treadWithUnit') as HTMLInputElement
        const minTread = screen.getByLabelText('tireList.minTreadWithUnit') as HTMLInputElement
        expect([tread.value, minTread.value]).toEqual(['11', '2'])
        fireEvent.change(tread, { target: { value: '.346' } })
        fireEvent.change(minTread, { target: { value: '0.0625' } })
        if (blur) {
          fireEvent.blur(tread)
          fireEvent.blur(minTread)
        }
        fireEvent.click(screen.getByText('common:save'))

        // 11/32 in = 8.73125 mm and 2/32 in = 1.5875 mm, not the 8.40 and 1.60 the fields started on.
        const payload = mutate.mock.calls[0][0]
        expect(payload.tread_depth_mm).toBe(8.73125)
        expect(payload.min_tread_mm).toBe(1.5875)
      }
    )

    it('still sends an untouched 8.40 and 1.60 back exactly', () => {
      gauged()
      const mutate = vi.fn()
      useUpsertTireMock.mockReturnValue({ mutate, isPending: false })

      render(<TireList vin="1HGCM82633A004352" />)
      fireEvent.click(screen.getByLabelText('tireList.edit'))
      fireEvent.click(screen.getByText('common:save'))

      const payload = mutate.mock.calls[0][0]
      expect(payload.tread_depth_mm).toBe(8.4)
      expect(payload.min_tread_mm).toBe(1.6)
    })
  })

  describe('reading history', () => {
    /* The API already ships every reading with the tire list and nothing
       rendered them: `readings` had zero consumers outside tests, so the
       history was fetched on every load and discarded. */
    const READING = {
      id: 11,
      tire_id: 1,
      vin: '1HGCM82633A004352',
      position: 'FL',
      recorded_at: '2026-08-25',
      // 160.934 km = 100 mi, 6.35 mm = 8/32 in, 248.21136 kPa = 36.0 psi.
      odometer_km: '160.934',
      tread_depth_mm: '6.35',
      pressure_kpa: '248.21136',
      notes: 'Slow leak, topped up',
      created_at: '2026-08-25T00:00:00',
    }

    it('opens the history from the card and converts every value', () => {
      useTiresMock.mockReturnValue({
        data: { tires: [{ ...STORED_FL_TIRE, readings: [READING] }], total: 1 },
        isLoading: false,
        error: null,
      })

      render(<TireList vin="1HGCM82633A004352" />)
      fireEvent.click(screen.getByRole('button', { name: 'tireList.historyOpen' }))

      const history = screen.getByRole('dialog')
      // Through the same adapters the card uses. A raw canonical value here
      // would put mm and kPa under a card reading in/PSI.
      expect(within(history).getByText('8/32 in')).toBeInTheDocument()
      expect(within(history).getByText('36.0 PSI')).toBeInTheDocument()
      expect(within(history).getByText('100 mi')).toBeInTheDocument()
      expect(within(history).getByText('Slow leak, topped up')).toBeInTheDocument()
    })

    it('shows the empty state for a tire with no readings', () => {
      render(<TireList vin="1HGCM82633A004352" />)
      fireEvent.click(screen.getByRole('button', { name: 'tireList.historyOpen' }))

      expect(screen.getByText('tireList.historyEmpty')).toBeInTheDocument()
    })
  })

  /**
   * Issue #179 was reported on this card: a full-card `absolute inset-0`
   * button sat over the DOT code and the readings, so a long-press on a phone
   * hit the button and nothing could be selected. The card now goes through
   * ClickableCard, which puts the handler on the card itself.
   *
   * jsdom has no layout and no long-press, so these pin STRUCTURE and HANDLERS
   * only: nothing stretched over the content, the click handled by the card, a
   * selection-end click ignored, the controls left alone. Whether the text is
   * really on top in a browser is the E2E half (G9).
   */
  describe('the mounted card opens its history without covering its text (#179)', () => {
    const HISTORY = 'tireList.historyTitle'

    function mountedCard(): HTMLElement {
      const card = screen.getByText('tireList.positions.FL').closest<HTMLElement>('.rounded-card')
      if (card === null) throw new Error('mounted tire card not found')
      return card
    }

    it('no overlay covers the mounted tire card', () => {
      // RED before G5: the history overlay is `absolute inset-0`, and the five
      // controls sit on `relative z-10` to clear it. With the overlay gone a
      // leftover `z-10` on Edit would paint the pencil over ClickableCard's
      // focus chip, which lives in the same top-right corner. This pins the
      // classes; how they paint is the browser's half.
      render(<TireList vin="1HGCM82633A004352" />)
      const card = mountedCard()
      const chip = within(card).getByRole('button', { name: 'tireList.historyOpen' })
        .parentElement as HTMLElement

      const everything = [card, ...Array.from(card.querySelectorAll<HTMLElement>('*'))]
      const tokensOf = (el: Element): string[] => (el.getAttribute('class') ?? '').split(/\s+/)

      const stretched = everything.filter((el) =>
        tokensOf(el).some((token) => token === 'inset-0' || token.endsWith(':inset-0')),
      )
      expect(stretched).toEqual([])
      const positioned = everything.filter((el) => tokensOf(el).includes('absolute'))
      expect(positioned).toEqual([chip])
      const lifted = everything.filter((el) => tokensOf(el).some((token) => /^z-\d+$/.test(token)))
      expect(lifted).toEqual([chip])
    })

    it("clicking the card's text opens the tire history", () => {
      // RED before G5: the overlay was a SIBLING of the text, so a click on
      // the DOT code bubbled through ancestors that had no handler. The jsdom
      // half: the handler is on the card now.
      render(<TireList vin="1HGCM82633A004352" />)
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

      fireEvent.click(screen.getByText('2324'))

      expect(screen.getByRole('dialog', { name: HISTORY })).toBeInTheDocument()
    })

    it('Edit, Log Reading, Dismount and Retire do their own thing and do not open history', () => {
      // Guard: passes before G5 too, because the overlay was a sibling and
      // couldn't hear these clicks. Mutant that kills it: drop
      // cameFromNestedControl from ClickableCard's handler, and every click
      // below also bubbles to the card and opens the history on top.
      const controls: ReadonlyArray<readonly [string, string]> = [
        ['tireList.edit', 'tireList.editTitleNamed'],
        ['tireList.addReading', 'tireList.readingTitle'],
        ['tireList.dismount', 'tireList.dismountTitle'],
        ['tireList.retire', 'tireList.retireTitle'],
      ]

      for (const [control, drawer] of controls) {
        const { unmount } = render(<TireList vin="1HGCM82633A004352" />)
        // Without this the rest passes on a card with no history route at all.
        expect(
          within(mountedCard()).getByRole('button', { name: 'tireList.historyOpen' }),
        ).toBeInTheDocument()

        fireEvent.click(within(mountedCard()).getByRole('button', { name: control }))

        expect(screen.getByRole('dialog', { name: drawer })).toBeInTheDocument()
        // hidden: true so a history drawer stacked UNDER the new one still counts.
        expect(screen.queryByRole('dialog', { name: HISTORY, hidden: true })).not.toBeInTheDocument()
        unmount()
      }
    })

    it('Fix still opens the history', () => {
      // Guard: Fix calls setHistoryTireId itself, on purpose. The card ignores
      // clicks from nested buttons, so dropping Fix's own onClick and trusting
      // the bubble opens nothing; that's the mutant that kills it. Opening it
      // twice with the same id is one render, so "exactly once" isn't
      // observable here.
      useTiresMock.mockReturnValue({
        data: { tires: [{ ...STORED_FL_TIRE, blocking_period_ids: [3], mount_periods: [] }], total: 1 },
        isLoading: false,
        error: null,
      })
      render(<TireList vin="1HGCM82633A004352" />)

      fireEvent.click(within(mountedCard()).getByRole('button', { name: 'tireList.fix' }))

      expect(screen.getByRole('dialog', { name: HISTORY })).toBeInTheDocument()
      expect(screen.getAllByRole('dialog')).toHaveLength(1)
    })

    it('ending a selection on the DOT code does not open history', () => {
      // The first half is a guard (no handler before G5, so nothing opened).
      // Mutant that kills it: skip isSelectingText in ClickableCard's handler.
      // The second half is RED before G5 and keeps the first from passing on
      // a card that never opens anything.
      render(<TireList vin="1HGCM82633A004352" />)
      const selection = vi.spyOn(window, 'getSelection').mockReturnValue({
        isCollapsed: false,
        toString: () => '2324',
      } as unknown as Selection)

      fireEvent.click(screen.getByText('2324'))
      expect(screen.queryByRole('dialog', { name: HISTORY, hidden: true })).not.toBeInTheDocument()

      selection.mockRestore()
      fireEvent.click(screen.getByText('2324'))
      expect(screen.getByRole('dialog', { name: HISTORY })).toBeInTheDocument()
    })

    it('the card is reachable by keyboard', () => {
      // Guard: the old overlay was a named button too. Mutant that kills it:
      // hand ClickableCard an empty label, and there's no button by this name.
      render(<TireList vin="1HGCM82633A004352" />)
      const button = within(mountedCard()).getByRole('button', { name: 'tireList.historyOpen' })

      button.focus()
      expect(button).toHaveFocus()
      fireEvent.click(button)

      expect(screen.getByRole('dialog', { name: HISTORY })).toBeInTheDocument()
    })
  })

  it('offers Fix only when a period blocks a figure, and Fix opens the history', () => {
    useTiresMock.mockReturnValue({
      data: { tires: [{ ...STORED_FL_TIRE, blocking_period_ids: [3], mount_periods: [] }], total: 1 },
      isLoading: false,
      error: null,
    })
    render(<TireList vin="1HGCM82633A004352" />)
    fireEvent.click(screen.getByText('tireList.fix'))
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  it('has no Fix control when nothing blocks', () => {
    render(<TireList vin="1HGCM82633A004352" />)
    expect(screen.queryByText('tireList.fix')).toBeNull()
  })

  it('offers Fix when history holds a contradiction even though nothing is blocked', () => {
    useTiresMock.mockReturnValue({
      data: {
        tires: [
          {
            ...STORED_FL_TIRE,
            blocking_period_ids: [],
            history_faults: [{ period_id: 3, code: 'overlapping_dates', counterpart_id: 4, message: 'M' }],
            mount_periods: [],
          },
        ],
        total: 1,
      },
      isLoading: false,
      error: null,
    })
    render(<TireList vin="1HGCM82633A004352" />)
    expect(screen.getByText('tireList.fix')).toBeInTheDocument()
  })

  it('offers Fix on a stored tire whose history holds a contradiction', () => {
    useTiresMock.mockReturnValue({
      data: {
        tires: [
          {
            ...STORED_FL_TIRE,
            position: null,
            blocking_period_ids: [],
            history_faults: [{ period_id: 3, code: 'overlapping_dates', counterpart_id: 4, message: 'M' }],
            mount_periods: [],
          },
        ],
        total: 1,
      },
      isLoading: false,
      error: null,
    })
    render(<TireList vin="1HGCM82633A004352" />)
    expect(screen.getByText('tireList.fix')).toBeInTheDocument()
  })

  const OPEN_PERIOD ={ id: 11, position: 'FL', mounted_on: '2026-04-10', dismounted_on: null, mounted_odometer_km: '152159.00', dismounted_odometer_km: null, is_assumed: false, observed_active_on: null, notes: null }

  it('the mounted card names its current mount', () => {
    useTiresMock.mockReturnValue({ data: { tires: [{ ...STORED_FL_TIRE, mount_periods: [OPEN_PERIOD] }], total: 1 }, isLoading: false, error: null })
    render(<TireList vin="1HGCM82633A004352" />)
    expect(screen.getByText('tireList.mountedOn')).toBeInTheDocument()
    expect(screen.getByText('tireList.mountedLine')).toBeInTheDocument()
  })

  it('says which half of the mount is unknown', () => {
    useTiresMock.mockReturnValue({ data: { tires: [{ ...STORED_FL_TIRE, mount_periods: [{ ...OPEN_PERIOD, mounted_on: null }] }], total: 1 }, isLoading: false, error: null })
    render(<TireList vin="1HGCM82633A004352" />)
    expect(screen.getByText('tireList.mountedOdometerOnly')).toBeInTheDocument()
  })

  it('says which half of the mount is unknown, the other way round', () => {
    useTiresMock.mockReturnValue({ data: { tires: [{ ...STORED_FL_TIRE, mount_periods: [{ ...OPEN_PERIOD, mounted_odometer_km: null }] }], total: 1 }, isLoading: false, error: null })
    render(<TireList vin="1HGCM82633A004352" />)
    expect(screen.getByText('tireList.mountedDateOnly')).toBeInTheDocument()
  })

  it('says both halves of the mount are unknown', () => {
    useTiresMock.mockReturnValue({ data: { tires: [{ ...STORED_FL_TIRE, mount_periods: [{ ...OPEN_PERIOD, mounted_on: null, mounted_odometer_km: null }] }], total: 1 }, isLoading: false, error: null })
    render(<TireList vin="1HGCM82633A004352" />)
    expect(screen.getByText('tireList.mountedUnknown')).toBeInTheDocument()
  })

  it('the stored card says since when, and where', () => {
    const stored = { ...STORED_FL_TIRE, position: null, storage_location: 'Garage shelf B', mount_periods: [{ ...OPEN_PERIOD, dismounted_on: '2026-09-01', dismounted_odometer_km: '160000.00' }] }
    useTiresMock.mockReturnValue({ data: { tires: [stored], total: 1 }, isLoading: false, error: null })
    render(<TireList vin="1HGCM82633A004352" />)
    expect(screen.getByText(/tireList\.inStorageSince/)).toBeInTheDocument()
    expect(screen.getByText(/Garage shelf B/)).toBeInTheDocument()
  })
})

describe('TireList – mount and dismount', () => {
  const MOUNTED = {
    id: 1,
    vin: '1HGCM82633A004352',
    position: 'FL',
    brand: 'Michelin',
    below_threshold: false,
    readings: [],
    mount_periods: [],
    distance_status: 'nothing_bounded',
    blocking_period_ids: [],
    created_at: '2026-01-01T00:00:00',
  }
  const STORED = { ...MOUNTED, id: 2, position: null, brand: 'Winter' }

  beforeEach(() => {
    vi.clearAllMocks()
    useAddTireReadingMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useDeleteTireMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
  })

  it('lists a stored tire without rendering an undefined position', () => {
    useTiresMock.mockReturnValue({
      data: { tires: [STORED], total: 1 },
      isLoading: false,
      error: null,
    })
    useUpsertTireMock.mockReturnValue({ mutate: vi.fn(), isPending: false })

    render(<TireList vin="1HGCM82633A004352" />)

    // A tire off the vehicle still has to be identifiable. Before the label
    // helper this rendered `positionLabels[null]`, i.e. nothing at all.
    expect(screen.getAllByText('tireList.inStorage').length).toBeGreaterThan(0)
    expect(screen.queryByText('undefined')).toBeNull()
  })

  it('does not carry a mount odometer over into the dismount drawer', () => {
    // These were one piece of state. A value typed into Mount and abandoned
    // reappeared in Dismount and silently became that period's closing bound
    // -- the number a tire's whole distance is computed from.
    useTiresMock.mockReturnValue({
      data: { tires: [MOUNTED, STORED], total: 2 },
      isLoading: false,
      error: null,
    })
    const mutate = vi.fn()
    useUpsertTireMock.mockReturnValue({ mutate, isPending: false })

    render(<TireList vin="1HGCM82633A004352" />)

    // Addressed by id: both drawers are in the DOM at once, so an accessible
    // name shared between them matches two fields.
    fireEvent.click(screen.getByText('tireList.mount'))
    const mountField = document.querySelector('#mount-odometer') as HTMLInputElement
    expect(mountField).toBeTruthy()
    fireEvent.change(mountField, { target: { value: '54321' } })
    fireEvent.click(screen.getAllByText('common:cancel')[0])

    fireEvent.click(screen.getByText('tireList.dismount'))
    const dismountField = document.querySelector('#dismount-odometer') as HTMLInputElement
    expect(dismountField).toBeTruthy()
    expect(dismountField.value).toBe('')
  })

  it('renders a per-status distance message rather than a zero', () => {
    // `nothing_bounded` is the state of EVERY tire immediately after
    // upgrading, so rendering it as "0 km" would tell every user their tires
    // had never been driven on.
    useTiresMock.mockReturnValue({
      data: { tires: [STORED], total: 1 },
      isLoading: false,
      error: null,
    })
    useUpsertTireMock.mockReturnValue({ mutate: vi.fn(), isPending: false })

    render(<TireList vin="1HGCM82633A004352" />)

    expect(screen.getByText('tireList.distance.nothingBounded')).toBeTruthy()
  })
})
