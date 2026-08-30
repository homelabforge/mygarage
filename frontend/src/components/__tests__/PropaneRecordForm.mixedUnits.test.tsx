/**
 * Task 3: the propane form's tank size, on the MASS token.
 *
 * `useUnitPreference().system` is D8-collapsed from VOLUME, so a client
 * resolving `{volume: 'L', mass: 'lb'}` was offered kilogramme tank sizes under
 * a `kg` label and stored the selection as kilogrammes, while every other screen
 * showed it pounds. The mirror account, `{volume: 'gal_us', mass: 'kg'}`, got
 * pounds it never asked for.
 *
 * The form's VOLUME and PRICE are already on the resolved set (task 2) and
 * their two remaining example hints belong to task 7 with the entry-grid shift.
 * This suite is about mass.
 *
 * Every case DRIVES the component and asserts RENDERED TEXT as well as the
 * posted body.
 *
 * Expected values are hand-written and derived in comments, never computed
 * through the code under test. `LBS_TO_KG` is 0.453592 (`utils/units.ts`).
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { ReactNode } from 'react'
import { waitFor, fireEvent } from '@testing-library/react'
import { render } from '../../__tests__/test-utils'
import { binarySystemFor, type UnitSet } from '../../types/units'

const createMock = vi.fn().mockResolvedValue({})
const updateMock = vi.fn().mockResolvedValue({})
vi.mock('../../hooks/queries/usePropaneRecords', () => ({
  useCreatePropaneRecord: () => ({ mutateAsync: createMock }),
  useUpdatePropaneRecord: () => ({ mutateAsync: updateMock }),
}))
vi.mock('../../hooks/useCurrencySymbol', () => ({ useCurrencySymbol: () => '$' }))

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
// mock is `t: (key) => key`, so the tank options would read the same whether
// their nominal size and unit were right, wrong, or missing entirely.
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

import { IMPERIAL_UNITS, METRIC_UNITS, UK_IMPERIAL_UNITS } from '../../__tests__/factories'
import PropaneRecordForm from '../PropaneRecordForm'

/** Litres, but pounds. `binarySystemFor('L')` is `'metric'`. */
const LITRES_POUNDS: UnitSet = { ...METRIC_UNITS, mass: 'lb' }
/** The mirror: gallons, but kilogrammes. `binarySystemFor('gal_us')` is `'imperial'`. */
const GALLONS_KILOS: UnitSet = { ...IMPERIAL_UNITS, mass: 'kg' }

const DEFAULT_PROPS = { vin: 'TEST12345678901234', onClose: vi.fn(), onSuccess: vi.fn() }
const propaneForm = (): HTMLFormElement =>
  document.getElementById('propane-record-form') as HTMLFormElement
const tankSelect = (): HTMLSelectElement =>
  document.getElementById('tank_size_kg') as HTMLSelectElement
const labelText = (id: string): string =>
  document.querySelector(`label[for="${id}"]`)?.textContent ?? ''
const optionLabels = (): string[] =>
  Array.from(tankSelect().options).slice(1).map((o) => o.textContent ?? '')

beforeEach(() => {
  vi.clearAllMocks()
  unitPrefMock.units = METRIC_UNITS
})

describe('PropaneRecordForm — the tank size follows units.mass', () => {
  it('★ a litres-and-pounds client picks tanks in pounds, under a pounds label', () => {
    // 9.07 / 0.453592 = 19.99593... lb, and the lb adapter carries two
    // decimals, so the option values are the same whole pounds the shipped
    // form offered: 20, 33, 100, 420.
    unitPrefMock.units = LITRES_POUNDS
    render(<PropaneRecordForm {...DEFAULT_PROPS} />)

    expect(Array.from(tankSelect().options).slice(1).map((o) => o.value)).toEqual([
      '20',
      '33',
      '100',
      '420',
    ])
    // ★ 'lb', not 'lbs'. `UnitFormatter.getWeightUnit('imperial')` answered
    // 'lbs' where the mass adapter, `getMassUnit` and the backend's own table
    // all answer 'lb'. Task 2 pinned the old string on purpose so this
    // migration could not change it silently; this is the deliberate change.
    expect(labelText('tank_size_kg')).toBe('propane.tankSize (lb)')
    expect(optionLabels()[0]).toContain('unit=lb')
    // The nominal marketing size travels with the unit: a 9.07 kg bottle is
    // sold as "20 lb" and as "9 kg".
    expect(optionLabels()[0]).toContain('size=20')
    expect(binarySystemFor(unitPrefMock.units.volume)).toBe('metric')
  })

  it('★ mirror: a gallons-and-kilogrammes client picks tanks in kilogrammes', () => {
    // The mirror pins the OTHER direction, so nothing above can be satisfied by
    // code that merely inverted the branch.
    unitPrefMock.units = GALLONS_KILOS
    render(<PropaneRecordForm {...DEFAULT_PROPS} />)

    expect(Array.from(tankSelect().options).slice(1).map((o) => o.value)).toEqual([
      '9.07',
      '14.97',
      '45.36',
      '190.51',
    ])
    expect(labelText('tank_size_kg')).toBe('propane.tankSize (kg)')
    expect(optionLabels()[0]).toContain('unit=kg')
    expect(optionLabels()[0]).toContain('size=9')
    expect(binarySystemFor(unitPrefMock.units.volume)).toBe('imperial')
  })

  it('★ a pounds client selecting a 20 lb bottle stores its canonical 9.07184 kg', async () => {
    // 20 lb x 0.453592 = 9.07184 kg. Before this slice the same selection
    // stored the raw 20, because `system` reads 'metric' off the litres: a
    // 20 lb bottle recorded as a 20 kg one.
    unitPrefMock.units = LITRES_POUNDS
    render(<PropaneRecordForm {...DEFAULT_PROPS} />)

    fireEvent.change(document.getElementById('date') as HTMLInputElement, {
      target: { value: '2026-03-01' },
    })
    fireEvent.change(tankSelect(), { target: { value: '20' } })
    fireEvent.change(document.getElementById('tank_quantity') as HTMLInputElement, {
      target: { value: '1' },
    })
    // 20 lb = 9.07184 kg x 1 x 1.968 L/kg = 17.85338... L, at the volume
    // field's OWN presentation. Task 7 moved the tank auto-calc onto
    // `u.volume.toInputValue`, the same two decimals a seeded value is shown
    // at and the same the read-only hint above the field quotes: it used to
    // write three, so the hint said 17.85 while the field it describes said
    // 17.853, which that hint's own comment forbids.
    await waitFor(() =>
      expect((document.getElementById('propane_liters') as HTMLInputElement).value).toBe('17.85')
    )

    fireEvent.submit(propaneForm())
    await waitFor(() => expect(createMock).toHaveBeenCalled())
    const payload = createMock.mock.calls[0][0] as Record<string, unknown>
    expect(payload.tank_size_kg).toBe(9.07184)
    expect(payload.tank_size_kg).not.toBe(20)
  })

  it('★ EDIT: a stored 9.07 kg tank reads back as the 20 lb option and an untouched save leaves it at 9.07', async () => {
    // The origin is what makes this exact. 9.07 kg seeds a pound field as
    // '20.00'; a <select> can only hand back '20', and converting that gives
    // 9.07184, so an account that opened a propane record and saved it would
    // have moved a tank size it never touched.
    unitPrefMock.units = LITRES_POUNDS
    render(
      <PropaneRecordForm
        {...DEFAULT_PROPS}
        record={
          {
            id: 21,
            vin: DEFAULT_PROPS.vin,
            date: '2026-03-01',
            propane_liters: '35.7',
            tank_size_kg: '9.07',
            tank_quantity: 2,
          } as never
        }
      />
    )

    expect(tankSelect().value).toBe('20')
    fireEvent.submit(propaneForm())
    await waitFor(() => expect(updateMock).toHaveBeenCalled())
    const payload = updateMock.mock.calls[0][0] as Record<string, unknown>
    expect(payload.tank_size_kg).toBe(9.07)
    expect(payload.tank_size_kg).not.toBe(9.07184)
  })

  it('★ the volume and price EXAMPLES name the reader\'s OWN gallon', async () => {
    // ★ FOUND BY MUTATION, not by reading. Pinning the example table to
    // `gal_us` killed NOTHING: these two placeholders had no test at all, which
    // is exactly the state ruling R5's structural exemption left them in (the
    // units gate cannot see a `placeholder` attribute on its comparison leg).
    // They were `system === 'imperial'` ternaries, and `system` is D8-collapsed
    // from volume, so both gallons took the same arm and a UK account read a
    // US-gallon example for a unit 20 percent larger.
    //
    // One physical fill, three vocabularies: 39.75 L at $0.766/L is 10.500 US
    // gallons at $2.899 and 8.744 imperial ones at $3.482.
    const placeholderOf = (id: string): string =>
      (document.getElementById(id) as HTMLInputElement).placeholder

    unitPrefMock.units = UK_IMPERIAL_UNITS
    const uk = render(<PropaneRecordForm {...DEFAULT_PROPS} />)
    expect(placeholderOf('propane_liters')).toBe('8.744')
    expect(placeholderOf('price_per_unit')).toBe('3.482')
    // The collapsed answer really does agree with the US one here, which is
    // what made this invisible.
    expect(binarySystemFor(unitPrefMock.units.volume)).toBe('imperial')
    uk.unmount()

    unitPrefMock.units = IMPERIAL_UNITS
    const us = render(<PropaneRecordForm {...DEFAULT_PROPS} />)
    expect(placeholderOf('propane_liters')).toBe('10.500')
    expect(placeholderOf('price_per_unit')).toBe('2.899')
    us.unmount()

    unitPrefMock.units = METRIC_UNITS
    render(<PropaneRecordForm {...DEFAULT_PROPS} />)
    expect(placeholderOf('propane_liters')).toBe('39.750')
    expect(placeholderOf('price_per_unit')).toBe('0.766')
  })

  it('a record with no tank size posts none, rather than a zero', async () => {
    unitPrefMock.units = LITRES_POUNDS
    render(
      <PropaneRecordForm
        {...DEFAULT_PROPS}
        record={
          {
            id: 22,
            vin: DEFAULT_PROPS.vin,
            date: '2026-03-01',
            propane_liters: '35.7',
          } as never
        }
      />
    )
    expect(tankSelect().value).toBe('')
    fireEvent.submit(propaneForm())
    await waitFor(() => expect(updateMock).toHaveBeenCalled())
    const payload = updateMock.mock.calls[0][0] as Record<string, unknown>
    expect(payload.tank_size_kg).toBeUndefined()
  })
})
