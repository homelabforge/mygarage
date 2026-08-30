import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, fireEvent, waitFor } from '@testing-library/react'
import { render } from '../../__tests__/test-utils'

const createMock = vi.fn().mockResolvedValue({})
const updateMock = vi.fn().mockResolvedValue({})

vi.mock('../../hooks/queries/useDEFRecords', () => ({
  useCreateDEFRecord: () => ({ mutateAsync: createMock }),
  useUpdateDEFRecord: () => ({ mutateAsync: updateMock }),
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
import DEFRecordForm from '../DEFRecordForm'

const DEFAULT_PROPS = { vin: 'TEST12345678901234', onClose: vi.fn(), onSuccess: vi.fn() }
const defForm = () => document.getElementById('def-record-form') as HTMLFormElement

beforeEach(() => {
  vi.clearAllMocks()
  unitPrefMock.system = 'metric'
  unitPrefMock.units = null
  UnitConverter.setGallonStandard('us')
})

describe('DEFRecordForm — structure', () => {
  it('renders every field control by id, INCLUDING odometer_km (fails if the restyle drops a field)', () => {
    render(<DEFRecordForm {...DEFAULT_PROPS} />)
    for (const id of ['date', 'odometer_km', 'fill_level', 'liters', 'price_per_unit', 'cost', 'source', 'brand', 'notes']) {
      expect(document.getElementById(id), id).not.toBeNull()
    }
  })

  it('a fill-level preset sets the numeric fill_level input (fails if the preset buttons lose their onClick)', () => {
    render(<DEFRecordForm {...DEFAULT_PROPS} />)
    // FILL_LEVEL_PRESETS "1/2" → value 50
    fireEvent.click(screen.getByRole('button', { name: '1/2' }))
    expect((document.getElementById('fill_level') as HTMLInputElement).value).toBe('50')
  })

  it('the footer submit button is wired to the form via form= association (fails if it becomes an onClick button)', () => {
    render(<DEFRecordForm {...DEFAULT_PROPS} />)
    const create = screen.getByRole('button', { name: 'common:create' })
    expect(create).toHaveAttribute('type', 'submit')
    expect(create).toHaveAttribute('form', 'def-record-form')
  })

  it('renders the edit title + Update label when given a record (fails if isEdit wiring breaks)', () => {
    render(<DEFRecordForm {...DEFAULT_PROPS} record={{ id: 5, vin: DEFAULT_PROPS.vin, date: '2026-02-10' } as never} />)
    expect(screen.getByText('def.editTitle')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'common:update' })).toBeInTheDocument()
  })
})

describe('DEFRecordForm — submit wiring + canonical payload', () => {
  it('CREATE: submitting sends the create mutation a CANONICAL payload — odometer registered + fill_level %→fraction (fails if submit is unwired, odometer loses its RHF register, or the % is sent raw as 50)', async () => {
    render(<DEFRecordForm {...DEFAULT_PROPS} />)
    fireEvent.change(document.getElementById('date') as HTMLInputElement, { target: { value: '2026-02-10' } })
    fireEvent.change(document.getElementById('odometer_km') as HTMLInputElement, { target: { value: '55000' } })
    fireEvent.change(document.getElementById('fill_level') as HTMLInputElement, { target: { value: '50' } })
    fireEvent.submit(defForm())
    await waitFor(() => expect(createMock).toHaveBeenCalled())
    // onSubmit canonicalizes odometer + fill_level (DEFRecordForm.tsx:135,139). Metric mode:
    // the distance round trip is identity, so odometer_km stays 55000; fill_level /100.
    expect(createMock).toHaveBeenCalledWith(expect.objectContaining({
      vin: 'TEST12345678901234',
      date: '2026-02-10',
      odometer_km: 55000,   // proves odometer stays RHF-registered + canonicalized — dropping register makes this field vanish
      fill_level: 0.5,      // 50% → 0.5 canonical fraction (onSubmit divides by 100)
    }))
    expect(updateMock).not.toHaveBeenCalled()
  })

  it('EDIT: submitting calls the UPDATE mutation (not create) with the record id + the FULL canonical payload incl. a changed field (fails if edit routes to create OR drops odometer/liters/fill_level)', async () => {
    // Meaningful fixture: odometer/liters/fill_level all populated (fill_level stored as the
    // 0–1 fraction 0.5 → the form displays it as 50). We change fill_level to 75 before submit.
    render(<DEFRecordForm {...DEFAULT_PROPS} record={{ id: 5, vin: DEFAULT_PROPS.vin, date: '2026-02-10', odometer_km: 55000, liters: 5.5, fill_level: 0.5 } as never} />)
    fireEvent.change(document.getElementById('fill_level') as HTMLInputElement, { target: { value: '75' } })
    fireEvent.submit(defForm())
    await waitFor(() => expect(updateMock).toHaveBeenCalled())
    // Metric mode: the distance and volume round trips are identity, so
    // odometer/liters pass through; the changed fill_level 75% → 0.75 (DEFRecordForm.tsx:139).
    expect(updateMock).toHaveBeenCalledWith(expect.objectContaining({
      id: 5,
      vin: 'TEST12345678901234',
      date: '2026-02-10',
      odometer_km: 55000,
      liters: 5.5,
      fill_level: 0.75,   // changed → proves the edit carries the edited value AND every canonical field
    }))
    expect(createMock).not.toHaveBeenCalled()
  })

  // Regression fence for the attached.length===0 gate (Task 9 follow-up): a
  // non-422 failure (network drop, 500, plain throw) carries NO field-level
  // detail at all, so applyServerErrors returns both `attached` and
  // `unhandled` empty. Gating the banner on `unhandled.length > 0` alone
  // silently drops this — the user sees nothing. Verified this fails under
  // that literal gate and passes under `attached.length === 0 ||
  // unhandled.length > 0` by temporarily reverting the source (see
  // task-9-report.md).
  it('shows a banner on a non-422 failure instead of staying silent (fails if the gate regresses to unhandled.length>0)', async () => {
    createMock.mockRejectedValueOnce(new Error('Network Error'))
    render(<DEFRecordForm {...DEFAULT_PROPS} />)
    fireEvent.change(document.getElementById('date') as HTMLInputElement, { target: { value: '2026-02-10' } })
    fireEvent.submit(defForm())
    await waitFor(() => expect(createMock).toHaveBeenCalled())
    await waitFor(() => expect(screen.getByText('Failed to {{action}}. {{message}}')).toBeInTheDocument())
  })
})

describe('DEFRecordForm — edit round-trip', () => {
  it('EDIT: a stored cost that is not volume x price survives opening the form (fails if the auto-calc effect fires on mount)', () => {
    // 5.5 L at $8.00/L is $44.00, but the receipt was $46.25 (the pump
    // rounded, or a fee rode along). Opening the record must not "correct" it.
    render(<DEFRecordForm {...DEFAULT_PROPS} record={{
      id: 7, vin: DEFAULT_PROPS.vin, date: '2026-02-10',
      liters: 5.5, price_per_unit: 8.0, cost: 46.25,
    } as never} />)
    expect((document.getElementById('cost') as HTMLInputElement).value).toBe('46.25')
  })

  it('EDIT: changing the volume still recalculates the cost (fails if the mount guard also blocks real user edits)', async () => {
    render(<DEFRecordForm {...DEFAULT_PROPS} record={{
      id: 7, vin: DEFAULT_PROPS.vin, date: '2026-02-10',
      liters: 5.5, price_per_unit: 8.0, cost: 46.25,
    } as never} />)
    fireEvent.change(document.getElementById('liters') as HTMLInputElement, { target: { value: '10' } })
    await waitFor(() => expect((document.getElementById('cost') as HTMLInputElement).value).toBe('80'))
  })
})

describe('DEFRecordForm — the gallon comes from the user, not the instance', () => {
  it('CREATE: a gal_uk user on a US-default instance stores volume AND price on the imperial gallon', async () => {
    // Defect L1: `toCanonicalLiters` used UnitConverter's instance-wide factor
    // while `priceToCanonical` used a hardcoded US gallon. Splitting the two
    // writes one payload with two gallons in it.
    UnitConverter.setGallonStandard('us')
    unitPrefMock.system = 'imperial'
    unitPrefMock.units = UK_IMPERIAL_UNITS

    render(<DEFRecordForm {...DEFAULT_PROPS} />)
    fireEvent.change(document.getElementById('date') as HTMLInputElement, { target: { value: '2026-02-10' } })
    fireEvent.change(document.getElementById('liters') as HTMLInputElement, { target: { value: '10' } })
    fireEvent.change(document.getElementById('price_per_unit') as HTMLInputElement, { target: { value: '6' } })
    fireEvent.submit(defForm())

    await waitFor(() => expect(createMock).toHaveBeenCalled())
    const payload = createMock.mock.calls[0][0] as Record<string, unknown>
    expect(payload.liters).toBe(45.461)             // 10 x 4.54609, at the schema's 3 dp
    expect(payload.price_per_unit).toBe(1.31981548979)  // 6 / 4.54609
    expect(UnitConverter.getGallonStandard()).toBe('us')
    // The row reconciles: the cost the user saw is price x volume in canonical
    // units too, which is only true when both used the same gallon.
    const ratio = (payload.price_per_unit as number) * (payload.liters as number) / (payload.cost as number)
    expect(ratio).toBeCloseTo(1, 4)
  })

  it('★ EDIT: a metric record with three stored decimals survives an untouched save', async () => {
    // ★ THE DISPLAY MOVED AND THE STORED VALUE STOPPED MOVING, which is the
    // whole of plan 3b task 7 on this field. The field used to be seeded with
    // the raw stored litres, so it read '45.461' and every OTHER rendering of
    // the same quantity read '45.46' (the `L` adapter carries two decimals, and
    // so does the backend's table). It now reads what the app reads. What that
    // costs is a digit on screen; what it buys is that the digit is not lost on
    // save, because the origin hands back the value the field was seeded from
    // rather than a re-conversion of the two decimals shown.
    unitPrefMock.system = 'metric'
    unitPrefMock.units = null

    render(<DEFRecordForm {...DEFAULT_PROPS} record={{
      id: 13, vin: DEFAULT_PROPS.vin, date: '2026-02-10', liters: 45.461, cost: 60,
    } as never} />)
    expect((document.getElementById('liters') as HTMLInputElement).value).toBe('45.46')

    fireEvent.submit(defForm())
    await waitFor(() => expect(updateMock).toHaveBeenCalled())
    expect((updateMock.mock.calls[0][0] as Record<string, unknown>).liters).toBe(45.461)
    // Not 45.46: the seeded display reconverted is what the shipped path posted,
    // and it is what this case exists to exclude.
    expect((updateMock.mock.calls[0][0] as Record<string, unknown>).liters).not.toBe(45.46)
  })

  it('★ EDIT: an ORDINARY gal_uk record survives an untouched save, off the entry grid', async () => {
    // ★ THE CASE THE FIXTURE BELOW CANNOT MAKE. 45.461 L and 1.31981548979 $/L
    // are `10 * 4.54609` and `6 / 4.54609`: exact round-trip fixed points, so
    // that test passed on the shipped code too and said nothing about ruling
    // R4. This one is an ordinary stored pair, and the shipped path moved both:
    //
    //   volume  22.712 / 4.54609 = 4.9959... -> two display dp  -> 5.00
    //           5 * 4.54609      = 22.73045  -> 3 wire decimals -> 22.73
    //   price   1.32 * 4.54609   = 6.00084   -> 3 display dp    -> 6.001
    //           6.001 / 4.54609  = 1.32003545904 at 12 significant digits
    UnitConverter.setGallonStandard('us')
    unitPrefMock.system = 'imperial'
    unitPrefMock.units = UK_IMPERIAL_UNITS

    render(<DEFRecordForm {...DEFAULT_PROPS} record={{
      id: 12, vin: DEFAULT_PROPS.vin, date: '2026-02-10',
      liters: 22.712, price_per_unit: 1.32, cost: 30.01,
    } as never} />)
    // The DISPLAY is quantised, which is what makes the payload meaningful.
    expect((document.getElementById('liters') as HTMLInputElement).value).toBe('5')
    expect((document.getElementById('price_per_unit') as HTMLInputElement).value).toBe('6.001')

    fireEvent.submit(defForm())
    await waitFor(() => expect(updateMock).toHaveBeenCalled())
    const payload = updateMock.mock.calls[0][0] as Record<string, unknown>
    expect(payload.liters).toBe(22.712)
    expect(payload.price_per_unit).toBe(1.32)
    // Named, so this cannot pass on a build where the arithmetic moved instead.
    expect(payload.liters).not.toBe(22.73)
    expect(payload.price_per_unit).not.toBe(1.32003545904)
  })

  it('EDIT: a gal_uk record already on the entry grid is a fixed point too', async () => {
    // The negative control: a pair the naive reconversion gets right on its
    // own, kept so the case above is not the only evidence.
    UnitConverter.setGallonStandard('us')
    unitPrefMock.system = 'imperial'
    unitPrefMock.units = UK_IMPERIAL_UNITS

    render(<DEFRecordForm {...DEFAULT_PROPS} record={{
      id: 11, vin: DEFAULT_PROPS.vin, date: '2026-02-10',
      liters: 45.461, price_per_unit: 1.31981548979, cost: 60,
    } as never} />)
    // Seeded in the USER's gallon: 45.461 / 4.54609 = 10, not 45.461 / 3.78541.
    expect((document.getElementById('liters') as HTMLInputElement).value).toBe('10')
    expect((document.getElementById('price_per_unit') as HTMLInputElement).value).toBe('6')

    fireEvent.submit(defForm())
    await waitFor(() => expect(updateMock).toHaveBeenCalled())
    const payload = updateMock.mock.calls[0][0] as Record<string, unknown>
    expect(payload.liters).toBe(45.461)
    expect(payload.price_per_unit).toBe(1.31981548979)
  })
})
