/**
 * Task 3 (v3.5.0 shape): the line-item editor's recurring-reminder distance
 * interval, which WRITES canonical km.
 *
 * The number typed into "Every (mi)" is converted by `RecurrenceFields` and
 * stored in `reminderDraft.interval_km`; `ServiceVisitForm` posts that field
 * inside `reminder.recurrence` as canonical kilometres and the backend anchors
 * the reminder on the visit. The conversion runs on `units.distance`, never on
 * the binary system collapsed from the volume choice, so a
 * `{volume: 'L', distance: 'mi'}` account entering 500 stores 804.672, not 500.
 *
 * Every case DRIVES the component and asserts RENDERED TEXT as well as the
 * value handed to `onChange`. Expected values are hand-written and derived in
 * comments, never computed through the code under test. `MILES_TO_KM` is
 * 1.609344 (`utils/units.ts`).
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
vi.mock('../../hooks/useReminders', () => ({
  useMaintenanceTypes: () => ({ data: [] }),
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

function itemWith(intervalKm?: number): ServiceVisitFormLineItem {
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
      mode: 'recurring',
      title: 'Oil change',
      due_date: undefined,
      recurrence: { interval_km: intervalKm },
      notes: undefined,
    },
  }
}

function renderEditor(item: ServiceVisitFormLineItem): void {
  render(
    <LineItemEditor
      item={item}
      index={0}
      vin="V1"
      supplies={[]}
      unitsBySupplyId={new Map()}
      failedInspections={[]}
      onChange={onChange}
      onRemove={vi.fn()}
      categories={['Maintenance']}
    />
  )
}

/** The distance interval input inside the recurring-reminder panel. */
const intervalInput = (): HTMLInputElement =>
  screen.getByLabelText(/recurrence\.everyDistance/) as HTMLInputElement

/** The distance interval field's own label, which carries the unit. */
const intervalLabel = (): string =>
  (screen.getByText(/recurrence\.everyDistance/).closest('label')?.textContent ?? '').replace(/\s+/g, ' ').trim()

function draftOf(call: unknown[]): { interval_km?: number } {
  return (call[2] as { recurrence: { interval_km?: number } }).recurrence
}

beforeEach(() => {
  vi.clearAllMocks()
  unitPrefMock.units = METRIC_UNITS
})

describe('LineItemEditor — the recurring-reminder distance interval is written on units.distance', () => {
  it('★ a 500-mile interval stores 804.672 km, not 500', () => {
    // 500 mi x 1.609344 = 804.672 km.
    unitPrefMock.units = LITRES_MILES
    renderEditor(itemWith())

    fireEvent.change(intervalInput(), { target: { value: '500' } })

    expect(onChange).toHaveBeenCalledTimes(1)
    const [index, fieldName] = onChange.mock.calls[0]
    expect(index).toBe(0)
    expect(fieldName).toBe('reminderDraft')
    expect(draftOf(onChange.mock.calls[0]).interval_km).toBe(804.672)
    expect(draftOf(onChange.mock.calls[0]).interval_km).not.toBe(500)
    expect(binarySystemFor(unitPrefMock.units.volume)).toBe('metric')
  })

  it('★ a stored 804.67 km reads back as 500 under a miles label', () => {
    unitPrefMock.units = LITRES_MILES
    renderEditor(itemWith(804.67))

    expect(intervalInput().value).toBe('500')
    expect(intervalLabel()).toContain('(mi)')
    expect(intervalInput().placeholder).toBe('recurrence.distancePlaceholder')
  })

  it('★ a field returned to its seeded display hands back the exact canonical value', () => {
    // 804.67 km shows as 500 mi. Typing 501 converts (806.28...), and typing
    // 500 again is the displayed quantity unchanged, so the stored value goes
    // back to 804.67, not to a re-conversion of 500 (804.672).
    unitPrefMock.units = LITRES_MILES
    renderEditor(itemWith(804.67))
    fireEvent.change(intervalInput(), { target: { value: '501' } })
    fireEvent.change(intervalInput(), { target: { value: '500' } })
    expect(onChange).toHaveBeenCalledTimes(2)
    expect(draftOf(onChange.mock.calls[0]).interval_km).not.toBe(804.67)
    expect(draftOf(onChange.mock.calls[1]).interval_km).toBe(804.67)
  })

  it('★ mirror: a gallons-and-kilometres client stores kilometres verbatim and reads them back', () => {
    unitPrefMock.units = GALLONS_KM
    renderEditor(itemWith(804.67))

    expect(intervalInput().value).toBe('805')
    expect(intervalLabel()).toContain('(km)')
    expect(binarySystemFor(unitPrefMock.units.volume)).toBe('imperial')

    fireEvent.change(intervalInput(), { target: { value: '500' } })
    expect(draftOf(onChange.mock.calls[0]).interval_km).toBe(500)
    expect(draftOf(onChange.mock.calls[0]).interval_km).not.toBe(804.67)
  })

  it('clearing the field removes the interval rather than storing a zero', () => {
    unitPrefMock.units = LITRES_MILES
    renderEditor(itemWith(804.67))
    fireEvent.change(intervalInput(), { target: { value: '' } })
    expect(draftOf(onChange.mock.calls[0]).interval_km).toBeUndefined()
  })

  it('the one-time mode shows a date field and no distance interval', () => {
    unitPrefMock.units = LITRES_MILES
    const item = itemWith()
    item.reminderDraft!.mode = 'once'
    renderEditor(item)
    expect(screen.queryByLabelText(/recurrence\.everyDistance/)).not.toBeInTheDocument()
    expect(screen.getByLabelText('lineItemEditor.misc.dueDate')).toBeInTheDocument()
  })

  it('enabling the reminder starts a RECURRING draft with no interval and the description as title', () => {
    unitPrefMock.units = LITRES_MILES
    const item = itemWith()
    item.reminderDraft = undefined
    renderEditor(item)
    fireEvent.click(screen.getByLabelText('lineItemEditor.misc.setReminder'))
    const [, field, draft] = onChange.mock.calls[0]
    expect(field).toBe('reminderDraft')
    expect(draft).toEqual({
      enabled: true,
      mode: 'recurring',
      title: 'Oil change',
      due_date: undefined,
      recurrence: {},
      notes: undefined,
    })
  })
})
