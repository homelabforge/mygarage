/**
 * Task 3: the warranty form's mileage limit, on the DISTANCE token.
 *
 * `useUnitPreference().system` is D8-collapsed from VOLUME, so a client
 * resolving `{volume: 'L', distance: 'mi'}` answered "no" to every
 * `system === 'imperial'` branch in this file: the limit was seeded in
 * kilometres, labelled `km`, and a typed mileage was stored verbatim as
 * kilometres.
 *
 * Every case DRIVES the component and asserts RENDERED TEXT as well as the
 * posted body. A right number under a wrong label is the same-screen defect
 * this slice removes, and a payload assertion alone cannot see it.
 *
 * Expected values are hand-written and derived in comments, never computed
 * through the code under test. `MILES_TO_KM` is 1.60934 (`utils/units.ts`).
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { waitFor, fireEvent } from '@testing-library/react'
import { render } from '../../__tests__/test-utils'
import { binarySystemFor, type UnitSet } from '../../types/units'
import type { WarrantyRecord } from '../../types/warranty'

const createMutateAsync = vi.fn().mockResolvedValue({})
const updateMutateAsync = vi.fn().mockResolvedValue({})
vi.mock('../../hooks/queries/useWarrantyRecords', () => ({
  useCreateWarrantyRecord: () => ({ mutateAsync: createMutateAsync }),
  useUpdateWarrantyRecord: () => ({ mutateAsync: updateMutateAsync }),
}))

// `system` is DERIVED from `units`, exactly as the real hook derives it. A mock
// pinning `system` to a literal could make every case below pass for the wrong
// reason: the whole defect is that `system` disagrees with `units.distance`,
// and a hardcoded `system` cannot express the disagreement (commit `e3f834f`).
const unitPrefMock = vi.hoisted(() => ({ units: null as unknown as UnitSet }))
vi.mock('../../hooks/useUnitPreference', () => ({
  useUnitPreference: () => ({
    system: binarySystemFor(unitPrefMock.units.volume),
    showBoth: false,
    units: unitPrefMock.units,
    gallonStandard: unitPrefMock.units.secondary_gallon,
  }),
}))

import { IMPERIAL_UNITS, METRIC_UNITS } from '../../__tests__/factories'
import WarrantyForm from '../WarrantyForm'

/** Litres, but miles. `binarySystemFor('L')` is `'metric'`. */
const LITRES_MILES: UnitSet = { ...METRIC_UNITS, distance: 'mi', speed: 'mph' }
/** The mirror: gallons, but kilometres. `binarySystemFor('gal_us')` is `'imperial'`. */
const GALLONS_KM: UnitSet = { ...IMPERIAL_UNITS, distance: 'km', speed: 'kmh' }

const DEFAULT_PROPS = { vin: 'V1', onClose: vi.fn(), onSuccess: vi.fn() }
const field = (id: string): HTMLInputElement => document.getElementById(id) as HTMLInputElement
const labelText = (id: string): string =>
  document.querySelector(`label[for="${id}"]`)?.textContent ?? ''
const warrantyForm = (): HTMLFormElement =>
  document.getElementById('warranty-form') as HTMLFormElement

beforeEach(() => {
  vi.clearAllMocks()
  unitPrefMock.units = METRIC_UNITS
})

/** A record whose km limit is NOT a whole number of miles, so the round trip is lossy. */
const RECORD = {
  id: 7,
  warranty_type: 'Powertrain',
  provider: 'Honda',
  start_date: '2025-01-01',
  end_date: '2029-01-01',
  mileage_limit_km: 96560,
  coverage_details: 'x',
  policy_number: 'P-9',
  notes: '',
} as unknown as WarrantyRecord

describe('WarrantyForm — the mileage limit follows units.distance', () => {
  it('★ EDIT: a litres-and-miles client reads the limit in miles, under a miles label', () => {
    // 96560 km / 1.60934 = 59999.7513... mi, shown at the mi adapter's zero
    // decimals as 60000.
    unitPrefMock.units = LITRES_MILES
    render(<WarrantyForm {...DEFAULT_PROPS} record={RECORD} />)

    expect(field('mileage_limit_km').value).toBe('60000')
    expect(labelText('mileage_limit_km')).toBe('warranty.mileageLimit (mi)')
    // The collapsed answer really does disagree, so the two above cannot be
    // passing because the collapse happened to agree.
    expect(binarySystemFor(unitPrefMock.units.volume)).toBe('metric')
  })

  it('★ CREATE: a typed mileage limit is stored as kilometres, not verbatim', async () => {
    // 50000 mi x 1.60934 = 80467 km. Before this slice the same entry stored
    // 50000, because `system` reads 'metric' off the litres.
    unitPrefMock.units = LITRES_MILES
    render(<WarrantyForm {...DEFAULT_PROPS} />)

    fireEvent.change(field('warranty_type'), { target: { value: 'Manufacturer' } })
    fireEvent.change(field('start_date'), { target: { value: '2026-01-01' } })
    fireEvent.change(field('mileage_limit_km'), { target: { value: '50000' } })
    fireEvent.submit(warrantyForm())

    await waitFor(() => expect(createMutateAsync).toHaveBeenCalledTimes(1))
    const payload = createMutateAsync.mock.calls[0][0] as Record<string, unknown>
    expect(payload.mileage_limit_km).toBe(80467)
    expect(payload.mileage_limit_km).not.toBe(50000)
  })

  it('★ EDIT (mirror): a gallons-and-kilometres client reads kilometres, and an untouched save stores the value back unchanged', async () => {
    // The mirror pins the OTHER direction, so nothing here can be satisfied by
    // code that merely inverted the branch.
    //
    // It is also where the origin becomes visible: 96560 km displays as 60000
    // mi and 60000 mi converts back to 96560.4 km, so before this slice an
    // imperial-volume account that opened this record and pressed Update moved
    // a stored limit it never touched.
    unitPrefMock.units = GALLONS_KM
    render(<WarrantyForm {...DEFAULT_PROPS} record={RECORD} />)

    expect(field('mileage_limit_km').value).toBe('96560')
    expect(labelText('mileage_limit_km')).toBe('warranty.mileageLimit (km)')
    expect(binarySystemFor(unitPrefMock.units.volume)).toBe('imperial')

    fireEvent.submit(warrantyForm())
    await waitFor(() => expect(updateMutateAsync).toHaveBeenCalledTimes(1))
    const payload = updateMutateAsync.mock.calls[0][0] as Record<string, unknown>
    expect(payload.mileage_limit_km).toBe(96560)
    expect(payload.mileage_limit_km).not.toBe(96560.4)
  })

  it('★ EDIT: a miles client saving an untouched record posts the stored kilometres, not a re-conversion', async () => {
    // 96560 km -> '60000' mi -> 96560.4 km. The origin hands the stored value
    // straight back, so reopening a warranty to fix a typo in the provider
    // does not nudge its mileage limit.
    unitPrefMock.units = LITRES_MILES
    render(<WarrantyForm {...DEFAULT_PROPS} record={RECORD} />)
    expect(field('mileage_limit_km').value).toBe('60000')

    fireEvent.change(field('provider'), { target: { value: 'Honda Ltd' } })
    fireEvent.submit(warrantyForm())
    await waitFor(() => expect(updateMutateAsync).toHaveBeenCalledTimes(1))
    const payload = updateMutateAsync.mock.calls[0][0] as Record<string, unknown>
    expect(payload.provider).toBe('Honda Ltd')
    expect(payload.mileage_limit_km).toBe(96560)
    expect(payload.mileage_limit_km).not.toBe(96560.4)
  })

  it('a limit cleared to blank posts no mileage limit at all', async () => {
    unitPrefMock.units = LITRES_MILES
    render(<WarrantyForm {...DEFAULT_PROPS} record={RECORD} />)
    fireEvent.change(field('mileage_limit_km'), { target: { value: '' } })
    fireEvent.submit(warrantyForm())
    await waitFor(() => expect(updateMutateAsync).toHaveBeenCalledTimes(1))
    const payload = updateMutateAsync.mock.calls[0][0] as Record<string, unknown>
    expect(payload.mileage_limit_km).toBeUndefined()
  })
})
