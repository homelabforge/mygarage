/**
 * TireList under a metric resolved set, and under a custom one.
 *
 * The imperial file next to this one cannot tell "the adapter resolved in32"
 * from "the component hardcodes thirty-seconds": every assertion there is
 * consistent with a component that simply always converts. These cases pin the
 * other side, including the per-quantity custom user the binary `system` cannot
 * describe (metric volume, imperial tread), where `useUnitPreference().system`
 * answers 'metric' and the tread field must still be in thirty-seconds.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import type { UnitSet } from '@/types/units'

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

/** The metric preset, written out rather than imported, per this repo's rule. */
const METRIC: UnitSet = {
  distance: 'km',
  speed: 'kmh',
  length: 'm',
  volume: 'L',
  consumption: 'l_100km',
  pressure: 'kpa',
  temperature: 'c',
  mass: 'kg',
  torque: 'nm',
  tread: 'mm',
  secondary_gallon: 'us',
}

const h = vi.hoisted(() => ({ units: null as unknown }))

vi.mock('../../hooks/useUnitPreference', () => ({
  useUnitPreference: () => ({
    // `system` stays 'metric' in every case below, including the custom one:
    // spec D8 derives it from VOLUME, which is litres throughout. A component
    // reading `system` instead of the resolved set cannot tell these apart.
    system: 'metric',
    showBoth: false,
    gallonStandard: 'us',
    units: h.units,
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

describe('TireList under a metric set', () => {
  beforeEach(() => {
    h.units = METRIC
    useUpsertTireMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useAddTireReadingMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useDeleteTireMock.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useTiresMock.mockReturnValue({
      data: { tires: [STORED_FL_TIRE], total: 1 },
      isLoading: false,
      error: null,
    })
  })

  it('reads the card tread in the unit the resolved set names', () => {
    // Rendered twice against the SAME stored 7.50 mm, because "still shows mm"
    // is true of a component that never converts at all. Only the second half
    // can tell the adapter is being consulted.
    const { unmount } = render(<TireList vin="1HGCM82633A004352" />)
    expect(screen.getByText('7.50 mm')).toBeInTheDocument()
    unmount()

    h.units = { ...METRIC, tread: 'in32' }
    render(<TireList vin="1HGCM82633A004352" />)

    expect(screen.getByText('9/32 in')).toBeInTheDocument()
    expect(screen.queryByText('7.50 mm')).not.toBeInTheDocument()
  })

  it('reads the card pressure in the same unit the form accepts', () => {
    render(<TireList vin="1HGCM82633A004352" />)

    // The binary `UnitFormatter.formatPressure` this component migrated off
    // rendered BAR for a metric user while its own form has always accepted
    // kPa, a disagreement its code comment used to document. D2 requires one
    // unit for entry and display. That method is gone as of phase 3b task 2,
    // so this asserts the adapter's answer rather than the difference.
    expect(screen.getByText('240 kPa')).toBeInTheDocument()
    expect(screen.queryByText('2.40 bar')).not.toBeInTheDocument()
  })

  it('shows canonical millimetres unconverted in the form, stepping by hundredths', () => {
    render(<TireList vin="1HGCM82633A004352" />)
    fireEvent.click(screen.getByLabelText('tireList.edit'))

    const tread = screen.getByLabelText('tireList.treadWithUnit') as HTMLInputElement
    expect(tread.value).toBe('7.50')
    expect(tread.step).toBe('0.01')
  })

  it('stores kPa unconverted, where the imperial path multiplies by 6.89476', () => {
    const mutate = vi.fn()
    useUpsertTireMock.mockReturnValue({ mutate, isPending: false })

    render(<TireList vin="1HGCM82633A004352" />)
    fireEvent.click(screen.getByLabelText('tireList.edit'))

    const pressure = screen.getByLabelText('tireList.pressureWithUnit') as HTMLInputElement
    // kPa has no decimals, so the field steps in whole kilopascals. This is the
    // assertion that is false at t=0 AND false before the change, where every
    // input carried a fixed step="0.1": the value and the payload below are
    // both what the unmigrated component already produced.
    expect(pressure.step).toBe('1')
    expect(pressure.value).toBe('240')

    fireEvent.change(pressure, { target: { value: '250' } })
    fireEvent.click(screen.getByText('common:save'))

    expect(mutate.mock.calls[0][0].pressure_kpa).toBe(250)
  })

  it('stores the typed millimetres when the tread field is edited', () => {
    const mutate = vi.fn()
    useUpsertTireMock.mockReturnValue({ mutate, isPending: false })

    render(<TireList vin="1HGCM82633A004352" />)
    fireEvent.click(screen.getByLabelText('tireList.edit'))

    // Same role as the step assertion above: mm renders at two decimals, which
    // the fixed step="0.1" never did, so this is false before the change while
    // the payload below is not.
    const tread = screen.getByLabelText('tireList.treadWithUnit') as HTMLInputElement
    expect(tread.step).toBe('0.01')

    fireEvent.change(tread, { target: { value: '8' } })
    fireEvent.click(screen.getByText('common:save'))

    expect(mutate.mock.calls[0][0].tread_depth_mm).toBe(8)
  })

  it('stores the typed kilometres unconverted, where the imperial path scales by 1.60934', () => {
    // The pair of the imperial `odometer_km === 160.934` test. Together they are
    // the two-sided control the deleted label test could not be.
    const mutate = vi.fn()
    useAddTireReadingMock.mockReturnValue({ mutate, isPending: false })

    render(<TireList vin="1HGCM82633A004352" />)
    fireEvent.click(screen.getByText('tireList.addReading'))

    // Same role as the two step assertions above, and for the same reason: the
    // payload below is what `Number('100')` produced before any of this work, so
    // on its own this test would pass with the fix absent. km has no decimals,
    // where every input used to carry a fixed step="0.1".
    const odo = screen.getByLabelText('tireList.odometerWithUnit') as HTMLInputElement
    expect(odo.step).toBe('1')

    fireEvent.change(odo, { target: { value: '100' } })
    fireEvent.click(screen.getByText('common:save'))

    expect(mutate.mock.calls[0][0].odometer_km).toBe(100)
  })

  it('reads the wear projection in the same unit the odometer field accepts', () => {
    // ★ D2 across two surfaces of one card, so this test reads BOTH of them.
    // `system` is collapsed from VOLUME, so this set answers 'metric' while
    // distance is miles: a projection left on
    // `UnitFormatter.formatDistance(..., system, ...)` renders "~1,000 km"
    // directly above an odometer field that is in miles and posts
    // `typed x 1.60934`. Two distances, one card, two units.
    h.units = { ...METRIC, distance: 'mi' }
    const mutate = vi.fn()
    useAddTireReadingMock.mockReturnValue({ mutate, isPending: false })
    useTiresMock.mockReturnValue({
      data: {
        tires: [{ ...STORED_FL_TIRE, projected_km_remaining: '1609.34' }],
        total: 1,
      },
      isLoading: false,
      error: null,
    })

    render(<TireList vin="1HGCM82633A004352" />)

    // Surface one, the card: 1,609.34 km / 1.60934 = 1000 mi, at mi's zero decimals.
    expect(screen.getByText('~1,000 mi')).toBeInTheDocument()
    expect(screen.queryByText('~1,000 km')).not.toBeInTheDocument()

    // Surface two, the field beneath it. Tread is seeded from the tire, so this
    // saves with only the odometer touched.
    fireEvent.click(screen.getByText('tireList.addReading'))
    fireEvent.change(screen.getByLabelText('tireList.odometerWithUnit'), {
      target: { value: '100' },
    })
    fireEvent.click(screen.getByText('common:save'))

    // 100 mi x 1.60934 = 160.934 km, the same unit the projection just read in.
    expect(mutate.mock.calls[0][0].odometer_km).toBe(160.934)
  })

  it('offers the canonical 2.0 mm default unconverted on an untouched Add form', () => {
    const mutate = vi.fn()
    useUpsertTireMock.mockReturnValue({ mutate, isPending: false })

    render(<TireList vin="1HGCM82633A004352" />)
    fireEvent.click(screen.getByText('tireList.add'))

    // The same default an imperial user sees as 3 thirty-seconds.
    expect((screen.getByLabelText('tireList.minTreadWithUnit') as HTMLInputElement).value).toBe(
      '2.00'
    )

    fireEvent.click(screen.getByText('common:save'))

    expect(mutate.mock.calls[0][0].min_tread_mm).toBe(2)
  })

  it('follows a custom tread override even though the binary system is metric', () => {
    // ★ The case `system` cannot express: litres, kPa, and thirty-seconds.
    h.units = { ...METRIC, tread: 'in32' }
    const mutate = vi.fn()
    useUpsertTireMock.mockReturnValue({ mutate, isPending: false })

    render(<TireList vin="1HGCM82633A004352" />)
    expect(screen.getByText('9/32 in')).toBeInTheDocument()

    fireEvent.click(screen.getByLabelText('tireList.edit'))
    // Pressure stays metric while tread is imperial: two quantities, two units.
    expect((screen.getByLabelText('tireList.pressureWithUnit') as HTMLInputElement).value).toBe(
      '240'
    )
    fireEvent.change(screen.getByLabelText('tireList.treadWithUnit'), {
      target: { value: '10' },
    })
    fireEvent.click(screen.getByText('common:save'))

    // 10/32 in x 0.79375 = 7.9375 mm
    expect(mutate.mock.calls[0][0].tread_depth_mm).toBe(7.9375)
  })
})
