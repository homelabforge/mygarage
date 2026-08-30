/**
 * Task 3: the line-item editor's reminder mileage, which WRITES canonical km.
 *
 * The plan's first revision filed this component as display-only. It is not:
 * the number typed into "distance until due" is converted here and stored in
 * `reminderDraft.due_mileage_km`, and `ServiceVisitForm` posts that field as
 * canonical kilometres. The conversion ran on `useUnitPreference().system`,
 * which spec D8 collapses from VOLUME, so a `{volume: 'L', distance: 'mi'}`
 * account entering a 500-mile reminder stored 500 km instead of 804.67.
 *
 * Every case DRIVES the component and asserts RENDERED TEXT as well as the
 * value handed to `onChange`.
 *
 * Expected values are hand-written and derived in comments, never computed
 * through the code under test. `MILES_TO_KM` is 1.60934 (`utils/units.ts`).
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { ReactNode } from 'react'
import { screen, fireEvent } from '@testing-library/react'
import { render } from '../../__tests__/test-utils'
import { binarySystemFor, type UnitSet } from '../../types/units'
import type { ServiceVisitFormLineItem } from '../../types/serviceVisit'

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
  useCurrencyPreference: () => ({ formatCurrency: (n: number) => `$${n}` }),
}))

// LOCAL i18n mock that RETAINS the interpolated values. The global setup.ts
// mock is `t: (key) => key`, so every label and hint below would render the
// same string whether its unit and numbers were right, wrong, or missing.
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
import LineItemEditor from '../LineItemEditor'

/** Litres, but miles. `binarySystemFor('L')` is `'metric'`. */
const LITRES_MILES: UnitSet = { ...METRIC_UNITS, distance: 'mi', speed: 'mph' }
/** The mirror: gallons, but kilometres. `binarySystemFor('gal_us')` is `'imperial'`. */
const GALLONS_KM: UnitSet = { ...IMPERIAL_UNITS, distance: 'km', speed: 'kmh' }

const onChange = vi.fn()

function itemWith(dueMileageKm?: number): ServiceVisitFormLineItem {
  return {
    tempId: -1,
    description: 'Oil change',
    category: 'Maintenance',
    cost: undefined,
    notes: '',
    is_inspection: false,
    inspection_result: '',
    inspection_severity: '',
    triggered_by_inspection_id: undefined,
    supplies_used: [],
    reminderDraft: {
      enabled: true,
      title: 'Oil change',
      reminder_type: 'mileage',
      due_date: undefined,
      due_mileage_km: dueMileageKm,
      notes: undefined,
    },
  }
}

function renderEditor(item: ServiceVisitFormLineItem, currentMileage?: number): void {
  render(
    <LineItemEditor
      item={item}
      index={0}
      vin="V1"
      supplies={[]}
      failedInspections={[]}
      onChange={onChange}
      onRemove={vi.fn()}
      categories={['Maintenance']}
      currentMileage={currentMileage}
    />
  )
}

/** The one numeric input inside the reminder panel. */
const mileageInput = (): HTMLInputElement =>
  screen.getByPlaceholderText(/lineItemEditor\.misc\.egValue/) as HTMLInputElement

/** The reminder mileage field's own label, which carries the unit. */
const mileageLabel = (): string =>
  screen.getByText(/lineItemEditor\.misc\.(distanceUntilDue|dueOdometer)/).textContent ?? ''

beforeEach(() => {
  vi.clearAllMocks()
  unitPrefMock.units = METRIC_UNITS
})

describe('LineItemEditor — the reminder mileage is written on units.distance', () => {
  it('★ a 500-mile reminder stores 804.67 km, not 500', () => {
    // 500 mi x 1.60934 = 804.67 km. This is the defect the plan named: before
    // this slice the same entry stored 500, because `system` reads 'metric'
    // off the litres and the km branch passes the typed number through.
    unitPrefMock.units = LITRES_MILES
    renderEditor(itemWith())

    fireEvent.change(mileageInput(), { target: { value: '500' } })

    expect(onChange).toHaveBeenCalledTimes(1)
    const [index, fieldName, draft] = onChange.mock.calls[0]
    expect(index).toBe(0)
    expect(fieldName).toBe('reminderDraft')
    expect((draft as { due_mileage_km: number }).due_mileage_km).toBe(804.67)
    expect((draft as { due_mileage_km: number }).due_mileage_km).not.toBe(500)
    expect(binarySystemFor(unitPrefMock.units.volume)).toBe('metric')
  })

  it('★ a stored 804.67 km reads back as 500 under a miles label, beside a miles example', () => {
    // The other half of the same round trip. Before this slice the field showed
    // 805 (804.67 km rounded) under a `km` label.
    unitPrefMock.units = LITRES_MILES
    renderEditor(itemWith(804.67))

    expect(mileageInput().value).toBe('500')
    expect(mileageLabel()).toBe('lineItemEditor.misc.dueOdometer unit=mi')
    // One example reading for every account: R5 calls a placeholder an EXAMPLE
    // value with nothing canonical to convert, and it was still being chosen by
    // the collapsed system.
    expect(mileageInput().placeholder).toBe('lineItemEditor.misc.egValue value=100000')
  })

  it('★ with a current odometer, the label, the interval and the target hint all read in miles', () => {
    // currentMileage 80467 km = 50000 mi exactly, plus a 500 mi interval:
    // the target is 50500 mi.
    unitPrefMock.units = LITRES_MILES
    renderEditor(itemWith(804.67), 80467)

    expect(mileageLabel()).toBe('lineItemEditor.misc.distanceUntilDue unit=mi')
    expect(mileageInput().value).toBe('500')
    expect(mileageInput().placeholder).toBe('lineItemEditor.misc.egValue value=5000')
    expect(screen.getByText(/targetCalc/).textContent).toBe(
      'lineItemEditor.misc.targetCalc current=50,000 interval=500 target=50,500 unit=mi'
    )
  })

  it('★ mirror: a gallons-and-kilometres client stores kilometres verbatim and reads them back', () => {
    // The mirror pins the OTHER direction, so nothing above can be satisfied by
    // code that merely inverted the branch. Before this slice a 500 typed here
    // was stored as 804.67 km for an account that entered kilometres.
    unitPrefMock.units = GALLONS_KM
    renderEditor(itemWith(804.67))

    expect(mileageInput().value).toBe('805')
    expect(mileageLabel()).toBe('lineItemEditor.misc.dueOdometer unit=km')
    expect(binarySystemFor(unitPrefMock.units.volume)).toBe('imperial')

    fireEvent.change(mileageInput(), { target: { value: '500' } })
    const [, , draft] = onChange.mock.calls[0]
    expect((draft as { due_mileage_km: number }).due_mileage_km).toBe(500)
    expect((draft as { due_mileage_km: number }).due_mileage_km).not.toBe(804.67)
  })

  it('clearing the field removes the mileage target rather than storing a zero', () => {
    unitPrefMock.units = LITRES_MILES
    renderEditor(itemWith(804.67))
    fireEvent.change(mileageInput(), { target: { value: '' } })
    const [, , draft] = onChange.mock.calls[0]
    expect((draft as { due_mileage_km?: number }).due_mileage_km).toBeUndefined()
  })
})
