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
//
// The resolved set is written out here rather than imported from the factories,
// so this file states the units it is asserting against. `useUnitFormat` is NOT
// mocked: the conversions below are the real adapters running.
vi.mock('../../hooks/useUnitPreference', () => ({
  useUnitPreference: () => ({
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
  }),
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

  it('posts a blank reading odometer as null, stepping the field in whole units', () => {
    // Replaces a test that asserted `tireList.odometerMi` present and
    // `tireList.odometerKm` absent. One interpolated key plus a mock `t` that
    // returns the key made both assertions unit-independent, so the name
    // claimed a property the body no longer exercised. The imperial
    // discriminator is the conversion test below; the metric one is its pair.
    const mutate = vi.fn()
    useAddTireReadingMock.mockReturnValue({ mutate, isPending: false })

    render(<TireList vin="1HGCM82633A004352" />)
    fireEvent.click(screen.getByText('tireList.addReading'))

    // mi renders at 0 decimals, so the spinner steps in whole miles.
    const odo = screen.getByLabelText('tireList.odometerWithUnit') as HTMLInputElement
    expect(odo.step).toBe('1')
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

    // 100 mi x 1.60934 = 160.934 km. The adapter does not round a canonical
    // write to two decimals the way `UnitConverter.milesToKm` did; it keeps the
    // exact conversion, as `UnitConverter.toCanonicalMetricString` already does
    // for every other form. The column is Numeric(10,2), so the server stores
    // 160.93 either way.
    expect(mutate.mock.calls[0][0].odometer_km).toBe(160.934)
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

    // 240 kPa / 6.89476 = 34.809..., and PSI renders at one decimal.
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
      // 36 PSI x 6.89476 = 248.21136 kPa, the field that WAS edited.
      expect(payload.pressure_kpa).toBe(248.21136)
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
      // 36 PSI x 6.89476 = 248.21136 kPa
      expect(payload.pressure_kpa).toBe(248.21136)
      // 100 mi x 1.60934 = 160.934 km, carried through as context.
      expect(payload.odometer_km).toBe(160.934)
    })

    it('steps the tread inputs by whole thirty-seconds', () => {
      render(<TireList vin="1HGCM82633A004352" />)
      fireEvent.click(screen.getByLabelText('tireList.edit'))

      // in32 has no decimals, so the fixed step="0.1" offered tenths of a
      // thirty-second of an inch.
      expect((screen.getByLabelText('tireList.treadWithUnit') as HTMLInputElement).step).toBe('1')
      expect(
        (screen.getByLabelText('tireList.minTreadWithUnit') as HTMLInputElement).step
      ).toBe('1')
      expect(
        (screen.getByLabelText('tireList.pressureWithUnit') as HTMLInputElement).step
      ).toBe('0.1')
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
      fireEvent.click(screen.getByLabelText('tireList.historyOpen'))

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
      fireEvent.click(screen.getByLabelText('tireList.historyOpen'))

      expect(screen.getByText('tireList.historyEmpty')).toBeInTheDocument()
    })

    it('keeps Edit and Log Reading out of the history overlay', () => {
      /* The overlay is a sibling button, not an ancestor, so a click on either
         control cannot reach it. Without that separation the card would open
         two drawers at once. */
      render(<TireList vin="1HGCM82633A004352" />)
      // Asserted first: without it the rest of this test passes on a card that
      // has no overlay at all, which is true before the feature exists.
      expect(screen.getByLabelText('tireList.historyOpen')).toBeInTheDocument()

      fireEvent.click(screen.getByLabelText('tireList.edit'))

      expect(screen.queryByText('tireList.historyEmpty')).not.toBeInTheDocument()
      expect(screen.getByText('tireList.editTitleNamed')).toBeInTheDocument()
    })
  })
})
