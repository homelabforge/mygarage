import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, fireEvent, waitFor } from '@testing-library/react'
import { render } from '../../__tests__/test-utils'

const createMock = vi.fn().mockResolvedValue({})
const updateMock = vi.fn().mockResolvedValue({})

vi.mock('../../hooks/queries/useDEFRecords', () => ({
  useCreateDEFRecord: () => ({ mutateAsync: createMock }),
  useUpdateDEFRecord: () => ({ mutateAsync: updateMock }),
}))
vi.mock('../../hooks/useUnitPreference', () => ({ useUnitPreference: () => ({ system: 'metric' }) }))
vi.mock('../../hooks/useCurrencySymbol', () => ({ useCurrencySymbol: () => '$' }))

import DEFRecordForm from '../DEFRecordForm'

const DEFAULT_PROPS = { vin: 'TEST12345678901234', onClose: vi.fn(), onSuccess: vi.fn() }
const defForm = () => document.getElementById('def-record-form') as HTMLFormElement

beforeEach(() => vi.clearAllMocks())

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
    // toCanonicalKm is identity (decimalSafe.ts:13), so odometer_km stays 55000; fill_level /100.
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
    // Metric mode: toCanonicalKm/toCanonicalLiters are identity (decimalSafe.ts:13,18), so
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
