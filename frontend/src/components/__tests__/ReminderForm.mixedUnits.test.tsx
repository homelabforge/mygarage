/**
 * Task 3: the reminder form's mileage interval, baseline and target hints.
 *
 * `useUnitPreference().system` is D8-collapsed from VOLUME, so a client
 * resolving `{volume: 'L', distance: 'mi'}` typed a mileage interval in miles
 * and stored it verbatim as kilometres, read its current mileage in kilometres
 * under a `mi` label, and was shown a target computed from the two.
 *
 * Every case DRIVES the component and asserts RENDERED TEXT as well as the
 * posted body.
 *
 * Expected values are hand-written and derived in comments, never computed
 * through the code under test. `MILES_TO_KM` is 1.60934 (`utils/units.ts`).
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { ReactNode } from 'react'
import { screen, waitFor, fireEvent } from '@testing-library/react'
import { render } from '../../__tests__/test-utils'
import { binarySystemFor, type UnitSet } from '../../types/units'
import type { Reminder } from '../../types/reminder'

const createMutateAsync = vi.fn().mockResolvedValue({})
const updateMutateAsync = vi.fn().mockResolvedValue({})
vi.mock('../../hooks/useReminders', () => ({
  useCreateReminder: () => ({ mutateAsync: createMutateAsync }),
  useUpdateReminder: () => ({ mutateAsync: updateMutateAsync }),
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('../../services/api', () => ({
  default: {
    get: vi.fn().mockResolvedValue({
      data: { usage_unit: 'distance', secondary_usage_enabled: false },
    }),
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

// LOCAL i18n mock that RETAINS the interpolated values. The global setup.ts
// mock is `t: (key) => key`, so a hint assertion against it would render the
// same string whether the numbers and the unit are right, wrong, or missing.
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, unknown>) =>
      options
        ? [key, ...Object.entries(options).map(([k, v]) => `${k}=${v}`)].join(' ')
        : key,
    i18n: { language: 'en', changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children: ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: () => {} },
}))

import { IMPERIAL_UNITS, METRIC_UNITS } from '../../__tests__/factories'
import ReminderForm from '../ReminderForm'

/** Litres, but miles. `binarySystemFor('L')` is `'metric'`. */
const LITRES_MILES: UnitSet = { ...METRIC_UNITS, distance: 'mi', speed: 'mph' }
/** The mirror: gallons, but kilometres. `binarySystemFor('gal_us')` is `'imperial'`. */
const GALLONS_KM: UnitSet = { ...IMPERIAL_UNITS, distance: 'km', speed: 'kmh' }

const BASE_PROPS = { vin: 'V1', onClose: vi.fn(), onSuccess: vi.fn() }
const field = (id: string): HTMLInputElement => document.getElementById(id) as HTMLInputElement
const labelText = (id: string): string =>
  document.querySelector(`label[for="${id}"]`)?.textContent ?? ''
const reminderForm = (): HTMLFormElement =>
  screen.getByRole('dialog').querySelector('form') as HTMLFormElement

beforeEach(() => {
  vi.clearAllMocks()
  unitPrefMock.units = METRIC_UNITS
})

/** 80467 km is exactly 50000 mi (50000 x 1.60934). */
const CURRENT_KM = 80467

describe('ReminderForm — mileage follows units.distance', () => {
  it('★ CREATE: a litres-and-miles client stores an interval typed in miles as kilometres', async () => {
    // 5000 mi x 1.60934 = 8046.7 km, added to the 80467 km baseline:
    // 80467 + 8046.7 = 88513.7 km. Before this slice the same entry added
    // 5000 km, because `system` reads 'metric' off the litres.
    unitPrefMock.units = LITRES_MILES
    render(<ReminderForm {...BASE_PROPS} currentMileage={CURRENT_KM} />)

    fireEvent.change(field('reminder-title'), { target: { value: 'Oil change' } })
    fireEvent.click(screen.getByText('reminderForm.typeMileage'))
    await waitFor(() => expect(field('reminder-mileage')).not.toBeNull())
    fireEvent.change(field('reminder-mileage'), { target: { value: '5000' } })

    // The label and the hint the user reads while typing it.
    expect(labelText('reminder-mileage')).toBe('reminder.distanceUntilDue * (mi)')
    expect(screen.getByText(/mileageTargetHint/).textContent).toBe(
      'reminderForm.mileageTargetHint current=50,000 interval=5,000 target=55,000 unit=mi'
    )

    fireEvent.submit(reminderForm())
    await waitFor(() => expect(createMutateAsync).toHaveBeenCalledTimes(1))
    const payload = createMutateAsync.mock.calls[0][0] as Record<string, unknown>
    expect(payload.due_mileage_km).toBe(88513.7)
    expect(payload.due_mileage_km).not.toBe(85467)
    expect(binarySystemFor(unitPrefMock.units.volume)).toBe('metric')
  })

  it('★ CREATE from last service: both the baseline and the interval convert', async () => {
    // 40000 mi x 1.60934 = 64373.6 km, 5000 mi x 1.60934 = 8046.7 km,
    // 64373.6 + 8046.7 = 72420.3 km. Before this slice: 40000 + 5000 = 45000.
    unitPrefMock.units = LITRES_MILES
    render(<ReminderForm {...BASE_PROPS} currentMileage={CURRENT_KM} />)

    fireEvent.change(field('reminder-title'), { target: { value: 'Tyres' } })
    fireEvent.click(screen.getByText('reminderForm.typeMileage'))
    await waitFor(() => expect(field('reminder-mileage')).not.toBeNull())
    fireEvent.click(screen.getByText('reminderForm.modeFromLast'))
    fireEvent.change(field('reminder-last-done-mileage'), { target: { value: '40000' } })
    fireEvent.change(field('reminder-mileage'), { target: { value: '5000' } })

    expect(labelText('reminder-last-done-mileage')).toBe('reminder.lastDoneMileage * (mi)')
    expect(screen.getByText(/mileageLastTargetHint/).textContent).toBe(
      'reminderForm.mileageLastTargetHint last=40,000 interval=5,000 target=45,000 unit=mi'
    )

    fireEvent.submit(reminderForm())
    await waitFor(() => expect(createMutateAsync).toHaveBeenCalledTimes(1))
    const payload = createMutateAsync.mock.calls[0][0] as Record<string, unknown>
    expect(payload.due_mileage_km).toBe(72420.3)
    expect(payload.due_mileage_km).not.toBe(45000)
  })

  it('★ EDIT: the remaining interval is shown in miles and an untouched save restores the exact target', async () => {
    // due 160935 km, current 80467 km -> 80468 km remaining, shown as
    // 80468 / 1.60934 = 50000.62... mi, i.e. 50001 at the mi adapter's zero
    // decimals. Re-converting 50001 mi gives 80468.6 km and a target of
    // 160935.6, so the origin is what keeps an untouched save exact.
    unitPrefMock.units = LITRES_MILES
    const reminder = {
      id: 3,
      title: 'Service',
      reminder_type: 'mileage',
      due_mileage_km: 160935,
      notes: '',
    } as unknown as Reminder
    render(<ReminderForm {...BASE_PROPS} reminder={reminder} currentMileage={CURRENT_KM} />)

    await waitFor(() => expect(field('reminder-mileage')).not.toBeNull())
    expect(field('reminder-mileage').value).toBe('50001')
    expect(labelText('reminder-mileage')).toBe('reminder.distanceUntilDue * (mi)')

    fireEvent.submit(reminderForm())
    await waitFor(() => expect(updateMutateAsync).toHaveBeenCalledTimes(1))
    const payload = updateMutateAsync.mock.calls[0][0] as Record<string, unknown>
    expect(payload.due_mileage_km).toBe(160935)
    expect(payload.due_mileage_km).not.toBe(160935.6)
  })

  it('★ EDIT (mirror): a gallons-and-kilometres client reads kilometres, and its untouched save is exact too', async () => {
    // The mirror pins the OTHER direction, so nothing above can be satisfied by
    // code that merely inverted the branch. Before this slice this account read
    // 50001 under a `km` label and saved a target of 160935.6.
    unitPrefMock.units = GALLONS_KM
    const reminder = {
      id: 3,
      title: 'Service',
      reminder_type: 'mileage',
      due_mileage_km: 160935,
      notes: '',
    } as unknown as Reminder
    render(<ReminderForm {...BASE_PROPS} reminder={reminder} currentMileage={CURRENT_KM} />)

    await waitFor(() => expect(field('reminder-mileage')).not.toBeNull())
    expect(field('reminder-mileage').value).toBe('80468')
    expect(labelText('reminder-mileage')).toBe('reminder.distanceUntilDue * (km)')
    expect(binarySystemFor(unitPrefMock.units.volume)).toBe('imperial')

    fireEvent.submit(reminderForm())
    await waitFor(() => expect(updateMutateAsync).toHaveBeenCalledTimes(1))
    const payload = updateMutateAsync.mock.calls[0][0] as Record<string, unknown>
    expect(payload.due_mileage_km).toBe(160935)
    expect(payload.due_mileage_km).not.toBe(160935.6)
  })

  it('★ the example mileage hint is one string for every account, not one per collapsed system', async () => {
    // R5 calls a placeholder an EXAMPLE value with nothing canonical to
    // convert, and the gate exempts it structurally on the comparison leg. It
    // was still chosen by the collapsed system, so a litres-and-miles account
    // read "e.g., 148000" beside a `mi` label. A reading that reads plausibly
    // in either unit needs no branch at all, which is what WarrantyForm's own
    // mileage placeholder has always done.
    unitPrefMock.units = LITRES_MILES
    const { unmount } = render(<ReminderForm {...BASE_PROPS} />)
    fireEvent.click(screen.getByText('reminderForm.typeMileage'))
    await waitFor(() => expect(field('reminder-mileage')).not.toBeNull())
    const milesHint = field('reminder-mileage').placeholder
    unmount()

    unitPrefMock.units = GALLONS_KM
    render(<ReminderForm {...BASE_PROPS} />)
    fireEvent.click(screen.getByText('reminderForm.typeMileage'))
    await waitFor(() => expect(field('reminder-mileage')).not.toBeNull())
    const kmHint = field('reminder-mileage').placeholder

    expect(milesHint).toBe('reminderForm.mileageExamplePlaceholder')
    expect(kmHint).toBe(milesHint)
  })
})
