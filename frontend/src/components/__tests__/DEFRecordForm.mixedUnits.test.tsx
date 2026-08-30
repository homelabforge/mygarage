/**
 * Task 3d: the DEF form's odometer, per quantity.
 *
 * The same regression commit `1b08e02` left in `FuelRecordForm`, in the file
 * beside it. That commit put this form's volume and price on the client's
 * resolved `UnitSet` (`:90-91`, `:122-123`) and left the odometer's seed,
 * submit and label on the binary `system === 'imperial'`. `system` is
 * D8-collapsed from VOLUME, so the odometer follows the client's gallon
 * choice rather than their distance choice.
 *
 * Both directions of that are wrong, and they are wrong differently:
 *
 *   litres + miles   -> `system` reads 'metric', so nothing converts. The
 *                       client is shown a field labelled `km` and will type
 *                       the mileage their dashboard shows into it.
 *   gallons + km     -> `system` reads 'imperial', so the form CONVERTS a
 *                       stored kilometre reading into miles and labels it
 *                       `mi`, for a client who asked for kilometres. That one
 *                       is an unambiguous wrong number in both directions of
 *                       the round trip.
 *
 * Every case drives the component and asserts RENDERED TEXT as well as the
 * posted payload. Expected values are hand-written and derived in comments.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, waitFor } from '@testing-library/react'
import { render } from '../../__tests__/test-utils'

const createMock = vi.fn().mockResolvedValue({})
const updateMock = vi.fn().mockResolvedValue({})

vi.mock('../../hooks/queries/useDEFRecords', () => ({
  useCreateDEFRecord: () => ({ mutateAsync: createMock }),
  useUpdateDEFRecord: () => ({ mutateAsync: updateMock }),
}))
vi.mock('../../hooks/useCurrencySymbol', () => ({ useCurrencySymbol: () => '$' }))

// `system` is DERIVED from `units`, exactly as the real hook derives it
// (`binarySystemFor(units.volume)`), per commit `e3f834f`. A mock that pinned
// it to a literal could not express the disagreement these cases exist to
// catch, and every one of them would pass for the wrong reason.
let units: import('@/types/units').UnitSet
vi.mock('../../hooks/useUnitPreference', async () => {
  const { binarySystemFor } = await import('@/types/units')
  return {
    useUnitPreference: () => ({
      system: binarySystemFor(units.volume),
      showBoth: false,
      units,
      gallonStandard: units.secondary_gallon,
    }),
  }
})

import { IMPERIAL_UNITS, METRIC_UNITS } from '../../__tests__/factories'
import { binarySystemFor, type UnitSet } from '../../types/units'
import { UNIT_ADAPTERS } from '../../utils/unitAdapters'
import DEFRecordForm from '../DEFRecordForm'

const DEFAULT_PROPS = { vin: 'TEST12345678901234', onClose: vi.fn(), onSuccess: vi.fn() }
const defForm = (): HTMLFormElement =>
  document.getElementById('def-record-form') as HTMLFormElement
const field = (id: string): HTMLInputElement => document.getElementById(id) as HTMLInputElement
const labelText = (id: string): string =>
  document.querySelector(`label[for="${id}"]`)?.textContent ?? ''

/** Litres, but miles. `binarySystemFor('L')` is 'metric'. */
const LITRES_MILES: UnitSet = { ...METRIC_UNITS, distance: 'mi', speed: 'mph' }
/** Gallons, but kilometres. `binarySystemFor('gal_us')` is 'imperial'. */
const GALLONS_KM: UnitSet = { ...IMPERIAL_UNITS, distance: 'km', speed: 'kmh' }

beforeEach(() => {
  vi.clearAllMocks()
  units = METRIC_UNITS
})

describe('DEFRecordForm — the odometer follows the distance token', () => {
  it('★ EDIT: volume, price and odometer all render in the units the client resolved', async () => {
    //   72420.3 km / 1.60934 = 45000 mi exactly (45000 x 1.60934 = 72420.3)
    //   5.5 L and $4.50/L are already litres: this client's volume IS canonical
    units = LITRES_MILES

    render(
      <DEFRecordForm
        {...DEFAULT_PROPS}
        record={{
          id: 5,
          vin: DEFAULT_PROPS.vin,
          date: '2026-02-10',
          odometer_km: 72420.3,
          liters: 5.5,
          price_per_unit: 4.5,
        } as never}
      />
    )

    expect(field('odometer_km').value).toBe('45000')
    expect(field('liters').value).toBe('5.5')
    expect(field('price_per_unit').value).toBe('4.5')

    expect(labelText('odometer_km')).toBe('common:mileage (mi)')
    expect(labelText('liters')).toBe('L')
    expect(labelText('price_per_unit')).toBe('fuel.pricePer/L')

    // The collapsed answer really does disagree with the odometer, so none of
    // the assertions above can be passing because it happened to agree.
    expect(binarySystemFor(units.volume)).toBe('metric')
  })

  it('★ EDIT: the seedUnitField odometer survives an untouched save; volume and price are identity here', async () => {
    // ★ NAMED FOR WHAT IT EXERCISES, for the same reason as the fuel form's
    // sibling: this unit set's volume is `L`, so the volume and price
    // assertions are identity by construction and only the odometer is
    // evidence of anything. The converting case is in
    // FuelRecordForm.gallonUnits.test.tsx.
    units = LITRES_MILES

    render(
      <DEFRecordForm
        {...DEFAULT_PROPS}
        record={{
          id: 5,
          vin: DEFAULT_PROPS.vin,
          date: '2026-02-10',
          odometer_km: 72420.3,
          liters: 5.5,
          price_per_unit: 4.5,
        } as never}
      />
    )
    expect(field('odometer_km').value).toBe('45000')
    // Stated rather than assumed: this is WHY the two below cannot fail here.
    expect(units.volume).toBe('L')

    fireEvent.submit(defForm())
    await waitFor(() => expect(updateMock).toHaveBeenCalled())

    const payload = updateMock.mock.calls[0][0] as Record<string, unknown>
    expect(payload.odometer_km).toBe(72420.3)
    expect(payload.liters).toBe(5.5)
    expect(payload.price_per_unit).toBe(4.5)
  })

  it('★ EDIT: an odometer BETWEEN two whole miles survives a save that never touched it', async () => {
    // The case above round-trips exactly, so it cannot tell a `seedUnitField`
    // origin from a re-conversion. This one can:
    //
    //   72420.5 km / 1.60934 = 45000.1242745 mi, shown as 45000 (mi has no
    //                          decimals)
    //   45000 mi x 1.60934   = 72420.3 km, which is NOT what was stored
    units = LITRES_MILES

    render(
      <DEFRecordForm
        {...DEFAULT_PROPS}
        record={{ id: 6, vin: DEFAULT_PROPS.vin, date: '2026-02-10', odometer_km: 72420.5 } as never}
      />
    )
    expect(field('odometer_km').value).toBe('45000')

    fireEvent.submit(defForm())
    await waitFor(() => expect(updateMock).toHaveBeenCalled())
    const payload = updateMock.mock.calls[0][0] as Record<string, unknown>
    expect(payload.odometer_km).toBe(72420.5)
    expect(payload.odometer_km).not.toBe(72420.3)

    // ★ The assumption that mechanism rests on, pinned rather than defended
    // against. `canonicalFromUnitField` compares the field against
    // `toInputValue`, i.e. `toFixed(precision)`, while this react-hook-form
    // NUMBER field can only offer `String(number)`. Those agree exactly at
    // zero decimals and would part company over a trailing zero. Folded into
    // this case rather than standing alone, because on its own it holds at
    // t=0 and would assert nothing.
    expect(UNIT_ADAPTERS.mi.precision).toBe(0)
    expect(UNIT_ADAPTERS.km.precision).toBe(0)
  })

  it('CREATE: a typed mileage reaches the API as canonical kilometres', async () => {
    //   45000 mi x 1.60934 = 72420.3 km
    units = LITRES_MILES

    render(<DEFRecordForm {...DEFAULT_PROPS} />)
    fireEvent.change(field('date'), { target: { value: '2026-02-10' } })
    fireEvent.change(field('odometer_km'), { target: { value: '45000' } })
    fireEvent.change(field('liters'), { target: { value: '5.5' } })
    fireEvent.submit(defForm())

    await waitFor(() => expect(createMock).toHaveBeenCalled())
    const payload = createMock.mock.calls[0][0] as Record<string, unknown>
    expect(payload.odometer_km).toBe(72420.3)
    expect(payload.liters).toBe(5.5)
  })

  it('the MIRROR client, gallons with kilometres, reads and writes the other way', async () => {
    // `system === 'imperial'` here, and the odometer must ignore it. Without
    // this case every assertion above could be satisfied by code that merely
    // inverted the binary branch. At `cd567d4` this field read 44999.81 under
    // a `mi` label for a client who chose kilometres.
    units = GALLONS_KM

    render(
      <DEFRecordForm
        {...DEFAULT_PROPS}
        record={{ id: 7, vin: DEFAULT_PROPS.vin, date: '2026-02-10', odometer_km: 72420 } as never}
      />
    )
    expect(field('odometer_km').value).toBe('72420')
    expect(labelText('odometer_km')).toBe('common:mileage (km)')
    expect(binarySystemFor(units.volume)).toBe('imperial')

    fireEvent.submit(defForm())
    await waitFor(() => expect(updateMock).toHaveBeenCalled())
    const payload = updateMock.mock.calls[0][0] as Record<string, unknown>
    expect(payload.odometer_km).toBe(72420)
  })

  it('a blank odometer posts nothing rather than zero', async () => {
    // A blank unit-bearing field that posts 0 poisons every derived distance
    // delta downstream, which is the shape of Task 1's F2a.
    units = LITRES_MILES

    render(
      <DEFRecordForm
        {...DEFAULT_PROPS}
        record={{ id: 8, vin: DEFAULT_PROPS.vin, date: '2026-02-10', odometer_km: 72420.3 } as never}
      />
    )
    expect(field('odometer_km').value).toBe('45000')

    fireEvent.change(field('odometer_km'), { target: { value: '' } })
    fireEvent.submit(defForm())
    await waitFor(() => expect(updateMock).toHaveBeenCalled())
    const payload = updateMock.mock.calls[0][0] as Record<string, unknown>
    expect(payload.odometer_km).toBeUndefined()
  })
})
