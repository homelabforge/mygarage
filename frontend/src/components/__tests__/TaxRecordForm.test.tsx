import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { screen, waitFor, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { render } from '../../__tests__/test-utils'
import { registeredFieldNames, submitAndSettle, validationError, whereA422Lands, dropQueuedOnces } from '../../__tests__/serverErrors'
import type { TaxRecord } from '../../types/tax'

const createMutateAsync = vi.fn().mockResolvedValue({})
const updateMutateAsync = vi.fn().mockResolvedValue({})
vi.mock('../../hooks/queries/useTaxRecords', () => ({
  useCreateTaxRecord: () => ({ mutateAsync: createMutateAsync }),
  useUpdateTaxRecord: () => ({ mutateAsync: updateMutateAsync }),
}))
// B1: TaxRecordForm renders CurrencyInputPrefix → useCurrencySymbol → useCurrencyPreference → useAuth
// (hooks/useCurrencyPreference.ts:24). The shared renderer provides NO AuthProvider, so mock
// useCurrencyPreference — the SAME deterministic mock T4/T6 use — to break the chain to useAuth; without
// it the suite throws `useAuth must be used within an AuthProvider` before reaching any assertion.
vi.mock('../../hooks/useCurrencyPreference', () => ({ useCurrencyPreference: () => ({ currencyCode: 'USD', locale: 'en-US', formatCurrency: vi.fn() }) }))

import TaxRecordForm from '../TaxRecordForm'

beforeEach(() => vi.clearAllMocks())

// A rejection a failed test queued but never used mustn't reach the next one.
afterEach(dropQueuedOnces(createMutateAsync, updateMutateAsync))

describe('TaxRecordForm — routing + exact payload (SDQ-C)', () => {
  it('create submits the COMPLETE payload INCLUDING vin (amount coerced to a number), and NEVER calls update (fails if a field is dropped, vin is omitted, the amount stays a string, or it misroutes)', async () => {
    const user = userEvent.setup()
    render(<TaxRecordForm vin="V1" onClose={vi.fn()} onSuccess={vi.fn()} />)
    await user.clear(screen.getByLabelText('tax.datePaid *'))
    await user.type(screen.getByLabelText('tax.datePaid *'), '2026-03-01')
    await user.selectOptions(screen.getByLabelText('taxRecordForm.type'), 'Registration')
    await user.clear(screen.getByLabelText('common:amount *'))
    await user.type(screen.getByLabelText('common:amount *'), '85.50')
    // renewal_date is an optional date whose default is '' — fill a valid date so the date schema
    // passes deterministically (an empty optional date is an edge this test deliberately avoids).
    await user.clear(screen.getByLabelText('tax.renewalDate'))
    await user.type(screen.getByLabelText('tax.renewalDate'), '2027-03-01')
    await user.clear(screen.getByLabelText('common:notes'))
    await user.type(screen.getByLabelText('common:notes'), 'note')
    await user.click(screen.getByRole('button', { name: 'common:create' }))
    await waitFor(() => expect(createMutateAsync).toHaveBeenCalledTimes(1))
    // toStrictEqual + toHaveProperty (mirrors B3) so a dropped field / omitted vin fails.
    const payload = createMutateAsync.mock.calls[0][0]
    expect(payload).toStrictEqual({
      vin: 'V1',
      date: '2026-03-01',
      tax_type: 'Registration',
      amount: 85.5,
      renewal_date: '2027-03-01',
      notes: 'note',
    })
    expect(payload).toHaveProperty('vin')
    expect(updateMutateAsync).not.toHaveBeenCalled()
  })

  it('edit submits the UPDATE payload — routing id + vin + edited amount — and NEVER calls create (fails if it misroutes or drops the id/vin)', async () => {
    const record = {
      id: 6, date: '2026-01-10', tax_type: 'Inspection', amount: 50, renewal_date: '2027-01-10', notes: 'y',
    } as unknown as TaxRecord
    const user = userEvent.setup()
    render(<TaxRecordForm vin="V1" record={record} onClose={vi.fn()} onSuccess={vi.fn()} />)
    await user.clear(screen.getByLabelText('common:amount *'))
    await user.type(screen.getByLabelText('common:amount *'), '75.25')
    await user.click(screen.getByRole('button', { name: 'common:update' }))
    await waitFor(() => expect(updateMutateAsync).toHaveBeenCalledTimes(1))
    // COMPLETE 7-property update object (id + all 6 payload fields incl. vin). The date/tax_type/
    // renewal_date/notes are untouched → their seeded defaults (formatDateForInput passes a
    // YYYY-MM-DD string through unchanged). toStrictEqual + toHaveProperty (mirrors B3) so a dropped
    // field or an omitted vin fails.
    const payload = updateMutateAsync.mock.calls[0][0]
    expect(payload).toStrictEqual({
      id: 6,
      vin: 'V1',
      date: '2026-01-10',
      tax_type: 'Inspection',
      amount: 75.25,
      renewal_date: '2027-01-10',
      notes: 'y',
    })
    expect(payload).toHaveProperty('vin')
    expect(createMutateAsync).not.toHaveBeenCalled()
  })

  it('the Field labels resolve to the controls carrying the expected ids (fails if a Field htmlFor/id association is dropped — including the currency carve-out)', () => {
    render(<TaxRecordForm vin="V1" onClose={vi.fn()} onSuccess={vi.fn()} />)
    expect(screen.getByLabelText('common:amount *')).toHaveAttribute('id', 'amount')
    expect(screen.getByLabelText('tax.datePaid *')).toHaveAttribute('id', 'date')
  })
})

describe('TaxRecordForm — amount field on NumberInput (Task 8)', () => {
  it('is a textbox, not a spinbutton, and accepts a comma decimal', async () => {
    const user = userEvent.setup()
    render(<TaxRecordForm vin="V1" onClose={vi.fn()} onSuccess={vi.fn()} />)
    const amountInput = screen.getByLabelText('common:amount *')
    expect(amountInput).toHaveAttribute('type', 'text')
    expect(screen.getByRole('textbox', { name: 'common:amount *' })).toBe(amountInput)

    await user.clear(screen.getByLabelText('tax.datePaid *'))
    await user.type(screen.getByLabelText('tax.datePaid *'), '2026-03-01')
    await user.selectOptions(screen.getByLabelText('taxRecordForm.type'), 'Registration')
    // renewal_date defaults to '' (not undefined), which fails makeDateSchema's
    // min(1) even though the field is .optional() — same edge the pre-existing
    // create test above deliberately avoids by filling it.
    await user.clear(screen.getByLabelText('tax.renewalDate'))
    await user.type(screen.getByLabelText('tax.renewalDate'), '2027-03-01')
    await user.type(amountInput, '85,50')
    await user.click(screen.getByRole('button', { name: 'common:create' }))

    await waitFor(() => expect(createMutateAsync).toHaveBeenCalledTimes(1))
    expect(createMutateAsync.mock.calls[0][0]).toMatchObject({ amount: 85.5 })
  })

  it('rejects unparseable text instead of silently discarding it', async () => {
    const user = userEvent.setup()
    render(<TaxRecordForm vin="V1" onClose={vi.fn()} onSuccess={vi.fn()} />)
    await user.clear(screen.getByLabelText('tax.datePaid *'))
    await user.type(screen.getByLabelText('tax.datePaid *'), '2026-03-01')
    await user.selectOptions(screen.getByLabelText('taxRecordForm.type'), 'Registration')
    await user.type(screen.getByLabelText('common:amount *'), 'abc')
    await user.click(screen.getByRole('button', { name: 'common:create' }))

    await waitFor(() =>
      expect(screen.getByText('common:validation.amount.invalid')).toBeInTheDocument()
    )
    expect(createMutateAsync).not.toHaveBeenCalled()
  })
})

describe('TaxRecordForm: the renewal date and type are optional and can be cleared', () => {
  it('creates a record with neither', async () => {
    const user = userEvent.setup()
    render(<TaxRecordForm vin="V1" onClose={vi.fn()} onSuccess={vi.fn()} />)
    await user.type(screen.getByLabelText('common:amount *'), '40')
    await user.click(screen.getByRole('button', { name: 'common:create' }))
    await waitFor(() => expect(createMutateAsync).toHaveBeenCalledTimes(1))
    expect(createMutateAsync.mock.calls[0][0]).toMatchObject({ amount: 40 })
    expect(createMutateAsync.mock.calls[0][0].renewal_date).toBeUndefined()
    expect(createMutateAsync.mock.calls[0][0].tax_type).toBeUndefined()
  })

  it('re-saves an untouched record that has neither', async () => {
    const record = {
      id: 8, date: '2026-01-10', tax_type: null, amount: 50, renewal_date: null, notes: null,
    } as unknown as TaxRecord
    const user = userEvent.setup()
    render(<TaxRecordForm vin="V1" record={record} onClose={vi.fn()} onSuccess={vi.fn()} />)
    await user.click(screen.getByRole('button', { name: 'common:update' }))
    await waitFor(() => expect(updateMutateAsync).toHaveBeenCalledTimes(1))
    expect(updateMutateAsync.mock.calls[0][0]).toMatchObject({ renewal_date: null, tax_type: null })
  })

  it('clearing both on edit posts null', async () => {
    const record = {
      id: 6, date: '2026-01-10', tax_type: 'Inspection', amount: 50, renewal_date: '2027-01-10', notes: 'y',
    } as unknown as TaxRecord
    const user = userEvent.setup()
    render(<TaxRecordForm vin="V1" record={record} onClose={vi.fn()} onSuccess={vi.fn()} />)
    await user.clear(screen.getByLabelText('tax.renewalDate'))
    await user.selectOptions(screen.getByLabelText('taxRecordForm.type'), '')
    await user.click(screen.getByRole('button', { name: 'common:update' }))
    await waitFor(() => expect(updateMutateAsync).toHaveBeenCalledTimes(1))
    expect(updateMutateAsync.mock.calls[0][0]).toMatchObject({ renewal_date: null, tax_type: null })
  })
})

describe('TaxRecordForm: a rejected save', () => {
  const taxForm = (): HTMLFormElement => document.getElementById('tax-record-form') as HTMLFormElement
  const banner = (): HTMLElement | null => screen.queryByText(/^Failed to tax\.saveAction\./)
  const openFilled = (): void => {
    render(<TaxRecordForm vin="V1" onClose={vi.fn()} onSuccess={vi.fn()} />)
    fireEvent.change(document.getElementById('date')!, { target: { value: '2026-03-01' } })
    fireEvent.change(document.getElementById('amount')!, { target: { value: '85.50' } })
  }

  it('a non-422 failure shows the banner and no field error', async () => {
    createMutateAsync.mockRejectedValueOnce(new Error('Network Error'))
    openFilled()
    await submitAndSettle(taxForm())

    expect(screen.getByText('Failed to tax.saveAction. Network Error')).toBeInTheDocument()
    expect(document.getElementById('amount-error')).toBeNull()
  })

  it('a 422 on amount shows under amount and no banner', async () => {
    createMutateAsync.mockRejectedValueOnce(validationError({ amount: 'Input should be greater than or equal to 0' }))
    openFilled()
    await submitAndSettle(taxForm())

    expect(document.getElementById('amount-error')).toHaveTextContent('Input should be greater than or equal to 0')
    expect(banner()).toBeNull()
  })

  // Named controls that aren't payload fields go here. None today.
  const UI_ONLY: string[] = []

  // Guard for knownFields drift and silent fields: a 422 on any field the form
  // registers has to show under that field. Mutant: drop a name from
  // knownFields and it banners.
  it('guard: a 422 on each field shows under it', async () => {
    openFilled()
    const names = registeredFieldNames(taxForm(), UI_ONLY)
    // An empty sweep would pass, so pin the names it must contain.
    expect(names).toEqual(expect.arrayContaining(['date', 'tax_type', 'amount', 'renewal_date', 'notes']))

    const wrong: string[] = []
    for (const name of names) {
      const got = await whereA422Lands(taxForm(), createMutateAsync, name, `bad ${name}`, banner)
      if (got !== 'field') wrong.push(`${name}: ${got}`)
    }
    expect(wrong).toEqual([])
  })
})
