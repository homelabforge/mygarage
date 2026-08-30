import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, fireEvent, waitFor } from '@testing-library/react'
import { render } from '../../__tests__/test-utils'

const createMock = vi.fn().mockResolvedValue({})
const updateMock = vi.fn().mockResolvedValue({})

vi.mock('../../hooks/queries/usePropaneRecords', () => ({
  useCreatePropaneRecord: () => ({ mutateAsync: createMock }),
  useUpdatePropaneRecord: () => ({ mutateAsync: updateMock }),
}))
const unitPrefMock = vi.hoisted(() => ({
  system: 'metric' as 'metric' | 'imperial',
  showBoth: false,
  // Set to pin an exact resolved set (a `gal_uk` user, say); left null the set
  // follows `system`, the way the real hook derives both on one rung.
  units: null as null | import('@/types/units').UnitSet,
}))
vi.mock('../../hooks/useUnitPreference', async () => {
  const { IMPERIAL_UNITS, METRIC_UNITS } = await import('@/__tests__/factories')
  return {
    useUnitPreference: () => ({
      system: unitPrefMock.system,
      showBoth: unitPrefMock.showBoth,
      units:
        unitPrefMock.units ??
        (unitPrefMock.system === 'imperial' ? IMPERIAL_UNITS : METRIC_UNITS),
    }),
  }
})
vi.mock('../../hooks/useCurrencySymbol', () => ({ useCurrencySymbol: () => '$' }))

import { UK_IMPERIAL_UNITS } from '../../__tests__/factories'
import { UnitConverter } from '../../utils/units'
import PropaneRecordForm from '../PropaneRecordForm'

const DEFAULT_PROPS = { vin: 'TEST12345678901234', onClose: vi.fn(), onSuccess: vi.fn() }
const propaneForm = () => document.getElementById('propane-record-form') as HTMLFormElement

beforeEach(() => {
  vi.clearAllMocks()
  unitPrefMock.system = 'metric'
  unitPrefMock.units = null
  UnitConverter.setGallonStandard('us')
})

describe('PropaneRecordForm — structure', () => {
  it('renders every field control by id (fails if the restyle drops a field)', () => {
    render(<PropaneRecordForm {...DEFAULT_PROPS} />)
    for (const id of ['date', 'tank_size_kg', 'tank_quantity', 'propane_liters', 'price_per_unit', 'cost', 'vendor', 'notes']) {
      expect(document.getElementById(id), id).not.toBeNull()
    }
  })

  it('keeps tank_size a NATIVE <select> with a placeholder + one option per TANK_SIZES entry AND the canonical-kg option values (fails if it becomes a custom combobox, loses options, or renumbers the values)', () => {
    render(<PropaneRecordForm {...DEFAULT_PROPS} />)
    const select = document.getElementById('tank_size_kg') as HTMLSelectElement
    expect(select.tagName).toBe('SELECT')
    expect(select.options.length).toBe(5)              // 4 TANK_SIZES + 1 empty placeholder
    expect(select.options[0].value).toBe('')            // placeholder
    // metric option values ARE the canonical kg weights (imperial would be rounded lbs)
    expect(Array.from(select.options).slice(1).map((o) => o.value)).toEqual(['9.07', '14.97', '45.36', '190.51'])
  })

  it('labels the tank-size field `lb` for a pounds user, the string task 3 changed on purpose', () => {
    // ★ THE DELIBERATE CHANGE. This assertion read '(lbs)' until plan 3b task 3
    // migrated the field to the mass adapter. `UnitFormatter.getWeightUnit`
    // answered 'lbs'; the mass adapter, `getMassUnit` and the backend's own
    // table all answer 'lb', and `unitAdapters.ts` records that its labels
    // match that table character for character precisely so a call-site
    // migration is not a visible regression. 'lbs' was the one place the old
    // binary API disagreed.
    //
    // Task 2 pinned the old string so this could not ship silently; the
    // manifest row routes the user-visible label change to task 9's changelog.
    unitPrefMock.system = 'imperial'
    render(<PropaneRecordForm {...DEFAULT_PROPS} />)
    const label = document.querySelector('label[for="tank_size_kg"]') as HTMLLabelElement
    expect(label.textContent).toContain('(lb)')
    expect(label.textContent).not.toContain('(lbs)')
  })

  it('the footer submit button is wired via form= association (fails if it becomes an onClick button)', () => {
    render(<PropaneRecordForm {...DEFAULT_PROPS} />)
    const create = screen.getByRole('button', { name: 'common:create' })
    expect(create).toHaveAttribute('type', 'submit')
    expect(create).toHaveAttribute('form', 'propane-record-form')
  })
})

describe('PropaneRecordForm — tank auto-calc + submit wiring', () => {
  it('selecting a tank size + quantity auto-calculates the propane volume into #propane_liters (fails if the calc effect is unwired)', async () => {
    render(<PropaneRecordForm {...DEFAULT_PROPS} />)
    fireEvent.change(document.getElementById('tank_size_kg') as HTMLSelectElement, { target: { value: '9.07' } })
    fireEvent.change(document.getElementById('tank_quantity') as HTMLInputElement, { target: { value: '2' } })
    // 9.07 kg × 2 × 1.968 L/kg = 35.699… → toFixed(3) → 35.7 (metric: no gallon conversion)
    await waitFor(() => expect((document.getElementById('propane_liters') as HTMLInputElement).value).toBe('35.7'))
  })

  it('CREATE: submit sends a CANONICAL payload with price_basis="per_volume" ALWAYS (fails if submit is unwired, values are not canonicalized, or the basis regresses to per_tank)', async () => {
    render(<PropaneRecordForm {...DEFAULT_PROPS} />)
    fireEvent.change(document.getElementById('date') as HTMLInputElement, { target: { value: '2026-03-01' } })
    fireEvent.change(document.getElementById('tank_size_kg') as HTMLSelectElement, { target: { value: '9.07' } })
    fireEvent.change(document.getElementById('tank_quantity') as HTMLInputElement, { target: { value: '2' } })
    await waitFor(() => expect((document.getElementById('propane_liters') as HTMLInputElement).value).toBe('35.7'))
    fireEvent.submit(propaneForm())
    await waitFor(() => expect(createMock).toHaveBeenCalled())
    expect(createMock).toHaveBeenCalledWith(expect.objectContaining({
      vin: 'TEST12345678901234', date: '2026-03-01',
      price_basis: 'per_volume', tank_size_kg: 9.07, tank_quantity: 2, propane_liters: 35.7,
    }))
    expect(updateMock).not.toHaveBeenCalled()
  })

  it('EDIT: submit calls the UPDATE mutation (not create) with the record id + the canonical payload (fails if edit routes to create OR loses vin/date/propane_liters/price_basis)', async () => {
    render(<PropaneRecordForm {...DEFAULT_PROPS} record={{ id: 9, vin: DEFAULT_PROPS.vin, date: '2026-03-01', propane_liters: '39.750' } as never} />)
    fireEvent.submit(propaneForm())
    await waitFor(() => expect(updateMock).toHaveBeenCalled())
    // onSubmit builds { id, ...payload } (PropaneRecordForm.tsx:167-186) and useUpdatePropaneRecord
    // strips id before the API call (usePropaneRecords.ts:40). Metric mode: toCanonicalLiters is
    // identity, so propane_liters '39.750' → 39.75; price_basis is ALWAYS 'per_volume'.
    // objectContaining({ id }) alone would survive losing vin/date/propane_liters/price_basis.
    expect(updateMock).toHaveBeenCalledWith(expect.objectContaining({
      id: 9,
      vin: DEFAULT_PROPS.vin,
      date: '2026-03-01',
      propane_liters: 39.75,
      price_basis: 'per_volume',
    }))
    expect(createMock).not.toHaveBeenCalled()
  })
})

describe('PropaneRecordForm — edit round-trip', () => {
  // The record the propane tab itself writes: tank size + quantity ARE stored,
  // and the volume was typed over the tank default (a partial refill of a
  // 33 lb bottle). Reopening it must not "recalculate" the user's numbers.
  const PARTIAL_REFILL = {
    id: 50,
    vin: DEFAULT_PROPS.vin,
    date: '2026-08-22',
    propane_liters: '8.500',
    tank_size_kg: '14.97',
    tank_quantity: 1,
    price_per_unit: '0.948',
    price_basis: 'per_volume',
    cost: '8.06',
    notes: 'Vendor: Tractor Supply',
  }

  it('EDIT: the stored volume and cost survive opening the form (fails if the tank auto-calc fires on mount and overwrites them)', () => {
    render(<PropaneRecordForm {...DEFAULT_PROPS} record={PARTIAL_REFILL as never} />)
    // Tank data is present, so a mount-time recalc would put 14.97 kg x 1 x
    // 1.968 = 29.467 L in the volume and 29.467 x 0.948 = 27.93 in the cost.
    expect((document.getElementById('propane_liters') as HTMLInputElement).value).toBe('8.5')
    expect((document.getElementById('cost') as HTMLInputElement).value).toBe('8.06')
  })

  it('EDIT: submitting an untouched record sends back the stored volume and cost (fails if the form saves recalculated numbers)', async () => {
    render(<PropaneRecordForm {...DEFAULT_PROPS} record={PARTIAL_REFILL as never} />)
    fireEvent.submit(propaneForm())
    await waitFor(() => expect(updateMock).toHaveBeenCalled())
    expect(updateMock).toHaveBeenCalledWith(expect.objectContaining({
      id: 50,
      propane_liters: 8.5,
      cost: 8.06,
    }))
  })

  it('EDIT: the vendor prefix is lifted out of notes exactly once (fails if the strip needs a trailing newline, which re-prefixes the vendor on every save)', async () => {
    render(<PropaneRecordForm {...DEFAULT_PROPS} record={PARTIAL_REFILL as never} />)
    expect((document.getElementById('vendor') as HTMLInputElement).value).toBe('Tractor Supply')
    expect((document.getElementById('notes') as HTMLTextAreaElement).value).toBe('')

    fireEvent.submit(propaneForm())
    await waitFor(() => expect(updateMock).toHaveBeenCalled())
    expect(updateMock).toHaveBeenCalledWith(expect.objectContaining({
      notes: 'Vendor: Tractor Supply',
    }))
  })

  it('EDIT: changing the tank size still recalculates the volume and cost (fails if the mount guard also blocks real user edits)', async () => {
    render(<PropaneRecordForm {...DEFAULT_PROPS} record={PARTIAL_REFILL as never} />)
    fireEvent.change(document.getElementById('tank_size_kg') as HTMLSelectElement, { target: { value: '9.07' } })
    // 9.07 kg x 1 x 1.968 = 17.850 L, x 0.948 = 16.92
    await waitFor(() => expect((document.getElementById('propane_liters') as HTMLInputElement).value).toBe('17.85'))
    await waitFor(() => expect((document.getElementById('cost') as HTMLInputElement).value).toBe('16.92'))
  })
})

describe('PropaneRecordForm — the gallon comes from the user, not the instance', () => {
  it('CREATE: a gal_uk user on a US-default instance stores volume AND price on the imperial gallon', async () => {
    UnitConverter.setGallonStandard('us')
    unitPrefMock.system = 'imperial'
    unitPrefMock.units = UK_IMPERIAL_UNITS

    render(<PropaneRecordForm {...DEFAULT_PROPS} />)
    fireEvent.change(document.getElementById('date') as HTMLInputElement, { target: { value: '2026-02-10' } })
    fireEvent.change(document.getElementById('propane_liters') as HTMLInputElement, { target: { value: '10' } })
    fireEvent.change(document.getElementById('price_per_unit') as HTMLInputElement, { target: { value: '6' } })
    fireEvent.submit(propaneForm())

    await waitFor(() => expect(createMock).toHaveBeenCalled())
    const payload = createMock.mock.calls[0][0] as Record<string, unknown>
    expect(payload.propane_liters).toBe(45.461)
    expect(payload.price_per_unit).toBe(1.31981548979)
    // Propane deliberately leaves `liters` unset and uses its own column, which
    // is why the corruption detector coalesces the two.
    expect(payload.liters).toBeUndefined()
    expect(UnitConverter.getGallonStandard()).toBe('us')
  })

  it('the tank auto-calc lands in the SAME unit the volume field is submitted in', async () => {
    // The tank row writes straight into propane_liters, so a volume computed
    // on the instance gallon would be submitted back through the user's one.
    UnitConverter.setGallonStandard('us')
    unitPrefMock.system = 'imperial'
    unitPrefMock.units = UK_IMPERIAL_UNITS

    render(<PropaneRecordForm {...DEFAULT_PROPS} />)
    fireEvent.change(document.getElementById('date') as HTMLInputElement, { target: { value: '2026-02-10' } })
    fireEvent.change(document.getElementById('tank_size_kg') as HTMLSelectElement, { target: { value: '20' } })
    fireEvent.change(document.getElementById('tank_quantity') as HTMLInputElement, { target: { value: '2' } })
    // 2 x 9.07 kg x 1.968 L/kg = 35.69952 L, which is 7.85 imperial gallons
    // (it would be 9.43 US ones).
    await waitFor(() =>
      expect((document.getElementById('propane_liters') as HTMLInputElement).value).toBe('7.85')
    )

    fireEvent.change(document.getElementById('price_per_unit') as HTMLInputElement, { target: { value: '6' } })
    await waitFor(() => expect((document.getElementById('cost') as HTMLInputElement).value).toBe('47.1'))
    fireEvent.submit(propaneForm())

    await waitFor(() => expect(createMock).toHaveBeenCalled())
    const payload = createMock.mock.calls[0][0] as Record<string, unknown>
    expect(payload.propane_liters).toBe(35.687)   // 7.85 x 4.54609, at 3 dp
    expect(payload.price_per_unit).toBe(1.31981548979)
    const ratio = (payload.price_per_unit as number) * (payload.propane_liters as number) / (payload.cost as number)
    expect(ratio).toBeCloseTo(1, 3)
  })

  it('★ EDIT: an ORDINARY gal_uk record survives an untouched save, off the entry grid', async () => {
    // ★ THE CASE THE FIXTURE BELOW CANNOT MAKE. 45.461 L and 1.31981548979 $/L
    // are exact round-trip fixed points, so that test passed on the shipped
    // code too. This pair is not, and the shipped path moved both:
    //
    //   volume  22.712 / 4.54609 = 4.9959... -> two display dp  -> 5.00
    //           5 * 4.54609      = 22.73045  -> 3 wire decimals -> 22.73
    //   price   1.32 * 4.54609   = 6.00084   -> 3 display dp    -> 6.001
    //           6.001 / 4.54609  = 1.32003545904 at 12 significant digits
    UnitConverter.setGallonStandard('us')
    unitPrefMock.system = 'imperial'
    unitPrefMock.units = UK_IMPERIAL_UNITS

    render(<PropaneRecordForm {...DEFAULT_PROPS} record={{
      id: 13, vin: DEFAULT_PROPS.vin, date: '2026-02-10',
      propane_liters: 22.712, price_per_unit: 1.32, price_basis: 'per_volume', cost: 30.01,
    } as never} />)
    expect((document.getElementById('propane_liters') as HTMLInputElement).value).toBe('5')
    expect((document.getElementById('price_per_unit') as HTMLInputElement).value).toBe('6.001')

    fireEvent.submit(propaneForm())
    await waitFor(() => expect(updateMock).toHaveBeenCalled())
    const payload = updateMock.mock.calls[0][0] as Record<string, unknown>
    expect(payload.propane_liters).toBe(22.712)
    expect(payload.price_per_unit).toBe(1.32)
    expect(payload.propane_liters).not.toBe(22.73)
    expect(payload.price_per_unit).not.toBe(1.32003545904)
  })

  it('★ EDIT: a legacy per_tank price is still re-read as the per_volume price it saves as', async () => {
    // ★ THE LEG A QUANTITY ORIGIN HAS NO PLACE FOR. A pre-fix record stored the
    // user's typed $/gal under basis='per_tank', so the seed shows it back
    // unconverted and the submit re-reads it as per_volume. That
    // reinterpretation is the intended migration; an origin that only compared
    // the NUMBER would call the field untouched and store 6 as a $/L price.
    UnitConverter.setGallonStandard('us')
    unitPrefMock.system = 'imperial'
    unitPrefMock.units = UK_IMPERIAL_UNITS

    render(<PropaneRecordForm {...DEFAULT_PROPS} record={{
      id: 14, vin: DEFAULT_PROPS.vin, date: '2026-02-10',
      propane_liters: 45.461, price_per_unit: 6, price_basis: 'per_tank', cost: 60,
    } as never} />)
    // Shown back exactly as typed, because per_tank converts nothing.
    expect((document.getElementById('price_per_unit') as HTMLInputElement).value).toBe('6')

    fireEvent.submit(propaneForm())
    await waitFor(() => expect(updateMock).toHaveBeenCalled())
    const payload = updateMock.mock.calls[0][0] as Record<string, unknown>
    expect(payload.price_basis).toBe('per_volume')
    // 6 / 4.54609 = 1.31981548979 $/L, and emphatically not the stored 6.
    expect(payload.price_per_unit).toBe(1.31981548979)
    expect(payload.price_per_unit).not.toBe(6)
  })

  it('EDIT: a gal_uk record already on the entry grid is a fixed point too', async () => {
    // The negative control: a pair the naive reconversion gets right on its
    // own, kept so the case above is not the only evidence.
    UnitConverter.setGallonStandard('us')
    unitPrefMock.system = 'imperial'
    unitPrefMock.units = UK_IMPERIAL_UNITS

    render(<PropaneRecordForm {...DEFAULT_PROPS} record={{
      id: 12, vin: DEFAULT_PROPS.vin, date: '2026-02-10',
      propane_liters: 45.461, price_per_unit: 1.31981548979, price_basis: 'per_volume', cost: 60,
    } as never} />)
    expect((document.getElementById('propane_liters') as HTMLInputElement).value).toBe('10')
    expect((document.getElementById('price_per_unit') as HTMLInputElement).value).toBe('6')

    fireEvent.submit(propaneForm())
    await waitFor(() => expect(updateMock).toHaveBeenCalled())
    const payload = updateMock.mock.calls[0][0] as Record<string, unknown>
    expect(payload.propane_liters).toBe(45.461)
    expect(payload.price_per_unit).toBe(1.31981548979)
  })
})
