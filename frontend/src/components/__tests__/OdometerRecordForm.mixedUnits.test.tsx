/**
 * Task 3: the odometer form, which is a form whose whole subject is a distance.
 *
 * `useUnitPreference().system` is D8-collapsed from VOLUME, so a client
 * resolving `{volume: 'L', distance: 'mi'}` was shown a reading in kilometres
 * under a `km` label and had its typed mileage stored verbatim as kilometres.
 * On this screen that is the entire record.
 *
 * Every case DRIVES the component and asserts RENDERED TEXT as well as the
 * posted body.
 *
 * Expected values are hand-written and derived in comments, never computed
 * through the code under test. `MILES_TO_KM` is 1.60934 (`utils/units.ts`).
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { waitFor, fireEvent } from '@testing-library/react'
import { render } from '../../__tests__/test-utils'
import { binarySystemFor, type UnitSet } from '../../types/units'
import type { OdometerRecord } from '../../types/odometer'

const createMutateAsync = vi.fn().mockResolvedValue({})
const updateMutateAsync = vi.fn().mockResolvedValue({})
vi.mock('../../hooks/queries/useOdometerRecords', () => ({
  useCreateOdometerRecord: () => ({ mutateAsync: createMutateAsync }),
  useUpdateOdometerRecord: () => ({ mutateAsync: updateMutateAsync }),
}))

// `system` is DERIVED from `units`, exactly as the real hook derives it. A mock
// pinning it to a literal could not express the disagreement these cases exist
// to catch (commit `e3f834f`).
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
import OdometerRecordForm from '../OdometerRecordForm'

/** Litres, but miles. `binarySystemFor('L')` is `'metric'`. */
const LITRES_MILES: UnitSet = { ...METRIC_UNITS, distance: 'mi', speed: 'mph' }
/** The mirror: gallons, but kilometres. `binarySystemFor('gal_us')` is `'imperial'`. */
const GALLONS_KM: UnitSet = { ...IMPERIAL_UNITS, distance: 'km', speed: 'kmh' }

const DEFAULT_PROPS = { vin: 'V1', onClose: vi.fn(), onSuccess: vi.fn() }
const field = (id: string): HTMLInputElement => document.getElementById(id) as HTMLInputElement
const labelText = (id: string): string =>
  document.querySelector(`label[for="${id}"]`)?.textContent ?? ''
const odometerForm = (): HTMLFormElement =>
  document.getElementById('odometer-record-form') as HTMLFormElement

/** A reading BETWEEN two whole miles, so the round trip is lossy in both directions. */
const RECORD = {
  id: 7,
  vin: 'V1',
  date: '2026-01-01',
  odometer_km: 72420.5,
  notes: '',
} as unknown as OdometerRecord

beforeEach(() => {
  vi.clearAllMocks()
  unitPrefMock.units = METRIC_UNITS
})

describe('OdometerRecordForm — the reading follows units.distance', () => {
  it('★ EDIT: a litres-and-miles client reads miles, under a miles label, with a miles example', () => {
    // 72420.5 km / 1.60934 = 45000.1242745... mi, shown at the mi adapter's
    // zero decimals as 45000.
    unitPrefMock.units = LITRES_MILES
    render(<OdometerRecordForm {...DEFAULT_PROPS} record={RECORD} />)

    expect(field('odometer_km').value).toBe('45000')
    expect(labelText('odometer_km')).toBe('common:mileage * (mi)')
    // The example reading is one quantity (72420 km) shown in the client's own
    // unit, not one of two literals chosen by a collapsed system: before this
    // slice a litres-and-miles client was offered '72420' under a `mi` label.
    expect(field('odometer_km').placeholder).toBe('45000')
    expect(binarySystemFor(unitPrefMock.units.volume)).toBe('metric')
  })

  it('★ CREATE: a typed reading is stored as kilometres, not verbatim', async () => {
    // 50000 mi x 1.60934 = 80467 km. Before this slice the same entry stored
    // 50000, because `system` reads 'metric' off the litres.
    unitPrefMock.units = LITRES_MILES
    render(<OdometerRecordForm {...DEFAULT_PROPS} />)

    fireEvent.change(field('date'), { target: { value: '2026-03-01' } })
    fireEvent.change(field('odometer_km'), { target: { value: '50000' } })
    fireEvent.submit(odometerForm())

    await waitFor(() => expect(createMutateAsync).toHaveBeenCalledTimes(1))
    const payload = createMutateAsync.mock.calls[0][0] as Record<string, unknown>
    expect(payload.odometer_km).toBe(80467)
    expect(payload.odometer_km).not.toBe(50000)
  })

  it('★ EDIT: a reading BETWEEN two whole miles survives a save that never touched it', async () => {
    // 72420.5 km shows as 45000 mi, and 45000 mi converts back to 72420.3 km.
    // Re-converting the display would move the reading 0.2 km every time the
    // record was opened and saved.
    unitPrefMock.units = LITRES_MILES
    render(<OdometerRecordForm {...DEFAULT_PROPS} record={RECORD} />)
    expect(field('odometer_km').value).toBe('45000')

    fireEvent.change(field('notes'), { target: { value: 'trip' } })
    fireEvent.submit(odometerForm())
    await waitFor(() => expect(updateMutateAsync).toHaveBeenCalledTimes(1))
    const payload = updateMutateAsync.mock.calls[0][0] as Record<string, unknown>
    expect(payload.notes).toBe('trip')
    expect(payload.odometer_km).toBe(72420.5)
    expect(payload.odometer_km).not.toBe(72420.3)
  })

  it('★ EDIT (mirror): a gallons-and-kilometres client reads kilometres, and the stored reading survives an untouched save', async () => {
    // The mirror pins the OTHER direction, so nothing above can be satisfied by
    // code that merely inverted the branch. 72420.5 km displays as 72421 (the
    // km adapter carries no decimals) and the origin still posts 72420.5.
    unitPrefMock.units = GALLONS_KM
    render(<OdometerRecordForm {...DEFAULT_PROPS} record={RECORD} />)

    expect(field('odometer_km').value).toBe('72421')
    expect(labelText('odometer_km')).toBe('common:mileage * (km)')
    expect(field('odometer_km').placeholder).toBe('72420')
    expect(binarySystemFor(unitPrefMock.units.volume)).toBe('imperial')

    fireEvent.submit(odometerForm())
    await waitFor(() => expect(updateMutateAsync).toHaveBeenCalledTimes(1))
    const payload = updateMutateAsync.mock.calls[0][0] as Record<string, unknown>
    expect(payload.odometer_km).toBe(72420.5)
    expect(payload.odometer_km).not.toBe(72421)
  })
})
