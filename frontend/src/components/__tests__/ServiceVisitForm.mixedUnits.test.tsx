/**
 * Task 3: the service-visit form's odometer, and the reminder mileage it posts.
 *
 * Two boundaries live on this screen. The odometer field is read and written
 * here; the reminder mileage is converted inside `LineItemEditor` and posted
 * from this form's submit as canonical kilometres. Both ran on
 * `useUnitPreference().system`, which spec D8 collapses from VOLUME, so a
 * `{volume: 'L', distance: 'mi'}` account typed miles and stored kilometres in
 * both places at once.
 *
 * The reminder case is deliberately end to end, through the REAL
 * `LineItemEditor`: the conversion and the write live in different files, and a
 * test that mocked the child could not see the pair disagree.
 *
 * Expected values are hand-written and derived in comments, never computed
 * through the code under test. `MILES_TO_KM` is 1.60934 (`utils/units.ts`).
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, waitFor, fireEvent } from '@testing-library/react'
import { render } from '../../__tests__/test-utils'
import { binarySystemFor, type UnitSet } from '../../types/units'
import type { ServiceVisit } from '../../types/serviceVisit'

const mockedApiGet = vi.fn()
const mockedApiPost = vi.fn().mockResolvedValue({ data: {} })
const mockedApiPut = vi.fn().mockResolvedValue({ data: {} })
vi.mock('../../services/api', () => ({
  default: {
    get: (...args: unknown[]) => mockedApiGet(...args),
    post: (...args: unknown[]) => mockedApiPost(...args),
    put: (...args: unknown[]) => mockedApiPut(...args),
  },
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
vi.mock('../../hooks/useCurrencyPreference', () => ({
  useCurrencyPreference: () => ({
    currencyCode: 'USD',
    locale: 'en-US',
    formatCurrency: () => '$0.00',
  }),
}))
vi.mock('../VendorSearch', () => ({ default: () => <div data-testid="vendor-search" /> }))
vi.mock('../ServiceVisitAttachmentUpload', () => ({ default: () => <div /> }))
vi.mock('../ServiceVisitAttachmentList', () => ({ default: () => <div /> }))
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }))

// ★ LineItemEditor is deliberately NOT mocked here. The other two suites stub
// it out; this one drives the real child, because the reminder mileage is
// converted there and written from here.

import { useCreateServiceVisit, useUpdateServiceVisit } from '../../hooks/queries/useServiceVisits'
import { IMPERIAL_UNITS, METRIC_UNITS } from '../../__tests__/factories'
import ServiceVisitForm from '../ServiceVisitForm'

vi.mock('../../hooks/queries/useServiceVisits', () => ({
  useCreateServiceVisit: vi.fn(),
  useUpdateServiceVisit: vi.fn(),
}))

const createMutateAsync = vi.fn().mockResolvedValue({})
const updateMutateAsync = vi.fn().mockResolvedValue({})

/** Litres, but miles. `binarySystemFor('L')` is `'metric'`. */
const LITRES_MILES: UnitSet = { ...METRIC_UNITS, distance: 'mi', speed: 'mph' }
/** The mirror: gallons, but kilometres. `binarySystemFor('gal_us')` is `'imperial'`. */
const GALLONS_KM: UnitSet = { ...IMPERIAL_UNITS, distance: 'km', speed: 'kmh' }

const DEFAULT_PROPS = { vin: 'TEST123', onClose: vi.fn(), onSuccess: vi.fn() }
const field = (id: string): HTMLInputElement => document.getElementById(id) as HTMLInputElement
const labelText = (id: string): string =>
  document.querySelector(`label[for="${id}"]`)?.textContent ?? ''
const drawerForm = (): HTMLFormElement =>
  screen.getByRole('dialog').querySelector('form') as HTMLFormElement

/** A visit whose reading is BETWEEN two whole miles, so the round trip is lossy. */
const VISIT = {
  id: 4,
  vin: 'TEST123',
  date: '2026-02-10T00:00:00',
  odometer_km: 72420.5,
  notes: '',
  line_items: [],
} as unknown as ServiceVisit

beforeEach(() => {
  vi.clearAllMocks()
  unitPrefMock.units = METRIC_UNITS
  vi.mocked(useCreateServiceVisit).mockReturnValue({
    mutateAsync: createMutateAsync,
  } as unknown as ReturnType<typeof useCreateServiceVisit>)
  vi.mocked(useUpdateServiceVisit).mockReturnValue({
    mutateAsync: updateMutateAsync,
  } as unknown as ReturnType<typeof useUpdateServiceVisit>)
  // `/vehicles/{vin}/odometer` backs useLatestMileage; everything else is the
  // vehicle fetch and the supplies list.
  mockedApiGet.mockImplementation((url: string) =>
    url.endsWith('/odometer')
      ? Promise.resolve({ data: { latest_odometer_km: null } })
      : Promise.resolve({ data: { items: [], supplies: [] } })
  )
})

describe('ServiceVisitForm — the odometer follows units.distance', () => {
  it('★ EDIT: a litres-and-miles client reads miles, under a miles label, with a miles example', async () => {
    // 72420.5 km / 1.60934 = 45000.1242745... mi, shown at the mi adapter's
    // zero decimals as 45000.
    unitPrefMock.units = LITRES_MILES
    render(<ServiceVisitForm {...DEFAULT_PROPS} visit={VISIT} />)
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())

    expect(field('service-odometer').value).toBe('45000')
    expect(labelText('service-odometer')).toBe('common:mileage (mi)')
    expect(field('service-odometer').placeholder).toBe('45000')
    expect(binarySystemFor(unitPrefMock.units.volume)).toBe('metric')
  })

  it('★ CREATE: a typed reading is stored as kilometres, not verbatim', async () => {
    // 50000 mi x 1.60934 = 80467 km. Before this slice the same entry stored
    // 50000, because `system` reads 'metric' off the litres.
    unitPrefMock.units = LITRES_MILES
    render(<ServiceVisitForm {...DEFAULT_PROPS} />)
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())

    fireEvent.change(field('service-odometer'), { target: { value: '50000' } })
    fireEvent.change(screen.getByPlaceholderText('lineItemEditor.misc.selectCategoryFirst'), {
      target: { value: 'Oil change' },
    })
    fireEvent.submit(drawerForm())

    await waitFor(() => expect(createMutateAsync).toHaveBeenCalledTimes(1))
    const payload = createMutateAsync.mock.calls[0][0] as Record<string, unknown>
    expect(payload.odometer_km).toBe(80467)
    expect(payload.odometer_km).not.toBe(50000)
  })

  it('★ EDIT (mirror): a gallons-and-kilometres client reads kilometres, and the stored reading survives an untouched save', async () => {
    // The mirror pins the OTHER direction. 72420.5 km displays as 72421 (the km
    // adapter carries no decimals) and the origin still posts 72420.5, where
    // re-converting the display would store 72421.
    unitPrefMock.units = GALLONS_KM
    render(<ServiceVisitForm {...DEFAULT_PROPS} visit={VISIT} />)
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())

    expect(field('service-odometer').value).toBe('72421')
    expect(labelText('service-odometer')).toBe('common:mileage (km)')
    expect(field('service-odometer').placeholder).toBe('72420')
    expect(binarySystemFor(unitPrefMock.units.volume)).toBe('imperial')

    // The edit path refuses to submit until the supplies list has hydrated (it
    // would otherwise wipe every logged usage), so wait for that rather than
    // for a fixed tick. A submit made before hydration sets a banner and calls
    // no mutation, which is why the count assertion still reads 1.
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalledWith('/supplies', expect.anything()))
    await waitFor(() => {
      fireEvent.submit(drawerForm())
      expect(updateMutateAsync).toHaveBeenCalledTimes(1)
    })
    const payload = updateMutateAsync.mock.calls[0][0] as Record<string, unknown>
    expect(payload.odometer_km).toBe(72420.5)
    expect(payload.odometer_km).not.toBe(72421)
  })
})

describe('ServiceVisitForm — the reminder mileage LineItemEditor writes', () => {
  it('★ END TO END: a 500-mile reminder is posted as 804.67 km, not 500', async () => {
    // The headline defect, driven through the real child. 500 mi x 1.60934 =
    // 804.67 km. `LineItemEditor` converts on change and this form posts the
    // result verbatim as `reminder.due_mileage_km`; before this slice a
    // litres-and-miles account stored the typed 500 as kilometres.
    unitPrefMock.units = LITRES_MILES
    render(<ServiceVisitForm {...DEFAULT_PROPS} />)
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())

    fireEvent.change(screen.getByPlaceholderText('lineItemEditor.misc.selectCategoryFirst'), {
      target: { value: 'Oil change' },
    })
    fireEvent.click(document.getElementById('reminder-0') as HTMLInputElement)
    // The draft opens as a date reminder; switch it to mileage.
    const typeSelect = screen
      .getByText('lineItemEditor.misc.reminderTypeLabel')
      .parentElement!.querySelector('select') as HTMLSelectElement
    fireEvent.change(typeSelect, { target: { value: 'mileage' } })

    const mileageInput = screen.getByPlaceholderText(
      'lineItemEditor.misc.egValue'
    ) as HTMLInputElement
    fireEvent.change(mileageInput, { target: { value: '500' } })

    fireEvent.submit(drawerForm())
    await waitFor(() => expect(createMutateAsync).toHaveBeenCalledTimes(1))
    const payload = createMutateAsync.mock.calls[0][0] as {
      line_items: { reminder?: { due_mileage_km?: number } }[]
    }
    expect(payload.line_items[0].reminder?.due_mileage_km).toBe(804.67)
    expect(payload.line_items[0].reminder?.due_mileage_km).not.toBe(500)
    expect(binarySystemFor(unitPrefMock.units.volume)).toBe('metric')
  })
})
