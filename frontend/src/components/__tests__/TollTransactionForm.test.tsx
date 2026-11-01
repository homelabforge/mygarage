import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, waitFor, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { render } from '../../__tests__/test-utils'
import { registeredFieldNames, submitAndSettle, validationError, whereA422Lands } from '../../__tests__/serverErrors'
import type { TollTag, TollTransaction } from '../../types/toll'

const createMutateAsync = vi.fn().mockResolvedValue({})
const updateMutateAsync = vi.fn().mockResolvedValue({})
vi.mock('../../hooks/queries/useTollRecords', () => ({
  useCreateTollTransaction: () => ({ mutateAsync: createMutateAsync }),
  useUpdateTollTransaction: () => ({ mutateAsync: updateMutateAsync }),
}))
// B1: TollTransactionForm renders CurrencyInputPrefix → useCurrencySymbol → useCurrencyPreference → useAuth
// (hooks/useCurrencyPreference.ts:24). The shared renderer provides NO AuthProvider, so mock
// useCurrencyPreference — the SAME deterministic mock T4/T6 use — to break the chain to useAuth; without
// it the suite throws `useAuth must be used within an AuthProvider` before reaching any assertion.
vi.mock('../../hooks/useCurrencyPreference', () => ({ useCurrencyPreference: () => ({ currencyCode: 'USD', locale: 'en-US', formatCurrency: vi.fn() }) }))

import TollTransactionForm from '../TollTransactionForm'

// A single active tag for the selected-tag path (status 'active' so the form's activeTollTags filter keeps it).
const activeTag = { id: 7, toll_system: 'E-ZPass', tag_number: 'ABC123', status: 'active' } as unknown as TollTag

beforeEach(() => vi.clearAllMocks())

describe('TollTransactionForm — routing + exact payload (SDQ-C)', () => {
  it('create — MANUAL-payment (toll_tag_id UNTOUCHED) submits the COMPLETE payload with toll_tag_id: null + vin, and NEVER calls update (fails if a field is dropped, the amount stays a string, vin is omitted, toll_tag_id is missing/wrong, or it misroutes)', async () => {
    const user = userEvent.setup()
    render(<TollTransactionForm vin="V1" tollTags={[]} onClose={vi.fn()} onSuccess={vi.fn()} />)
    // The currency amount is the G4(c) raw <input> inside a <Field id="amount"> — getByLabelText
    // resolves it through the sr-visible label association (fails if the Field htmlFor/id link drops).
    await user.clear(screen.getByLabelText('common:date *'))
    await user.type(screen.getByLabelText('common:date *'), '2026-02-01')
    await user.clear(screen.getByLabelText('common:amount *'))
    await user.type(screen.getByLabelText('common:amount *'), '4.5')
    await user.clear(screen.getByLabelText('toll.location *'))
    await user.type(screen.getByLabelText('toll.location *'), 'Main St Toll')
    await user.clear(screen.getByLabelText('common:notes'))
    await user.type(screen.getByLabelText('common:notes'), 'note')
    // toll_tag_id select left UNTOUCHED — the real "manual payment" path. With the B2 valueAsNumber fix the
    // empty selection ('') coerces to NaN, which tollTransactionSchema transforms to undefined (schema
    // tollTransaction.ts:10-14). WITHOUT the fix the '' is rejected as a string and NO mutation fires.
    await user.click(screen.getByRole('button', { name: 'toll.addTransaction' }))
    await waitFor(() => expect(createMutateAsync).toHaveBeenCalledTimes(1))
    // B3: capture the call and assert strictly. toStrictEqual distinguishes a MISSING key from an explicit
    // `undefined` one (Vitest loose equality does NOT), and the explicit toHaveProperty pins the key's
    // presence — so a silently-dropped toll_tag_id fails, which a plain toHaveBeenCalledWith would not.
    const payload = createMutateAsync.mock.calls[0][0]
    expect(payload).toStrictEqual({
      transaction_date: '2026-02-01',
      amount: 4.5,
      location: 'Main St Toll',
      toll_tag_id: null,
      notes: 'note',
      vin: 'V1',
    })
    expect(payload).toHaveProperty('toll_tag_id')
    expect(updateMutateAsync).not.toHaveBeenCalled()
  })

  it('create — with a SELECTED tag submits toll_tag_id as the NUMERIC id (fails if the B2 valueAsNumber fix is missing so the id stays a string, or the selection is dropped)', async () => {
    const user = userEvent.setup()
    render(<TollTransactionForm vin="V1" tollTags={[activeTag]} onClose={vi.fn()} onSuccess={vi.fn()} />)
    await user.clear(screen.getByLabelText('common:date *'))
    await user.type(screen.getByLabelText('common:date *'), '2026-02-01')
    await user.clear(screen.getByLabelText('common:amount *'))
    await user.type(screen.getByLabelText('common:amount *'), '4.5')
    await user.clear(screen.getByLabelText('toll.location *'))
    await user.type(screen.getByLabelText('toll.location *'), 'Main St Toll')
    // toll_tag_id is NOT required, so its Field label carries no ' *' suffix.
    await user.selectOptions(screen.getByLabelText('toll.tollTag'), '7')
    await user.click(screen.getByRole('button', { name: 'toll.addTransaction' }))
    await waitFor(() => expect(createMutateAsync).toHaveBeenCalledTimes(1))
    const payload = createMutateAsync.mock.calls[0][0]
    // notes left untouched ⇒ its '' default. valueAsNumber turns the selected value '7' into the number 7.
    expect(payload).toStrictEqual({
      transaction_date: '2026-02-01',
      amount: 4.5,
      location: 'Main St Toll',
      toll_tag_id: 7,
      notes: '',
      vin: 'V1',
    })
    expect(payload).toHaveProperty('toll_tag_id')
    expect(updateMutateAsync).not.toHaveBeenCalled()
  })

  it('edit submits the UPDATE payload — routing id + edited field, NO vin — and NEVER calls create (fails if it misroutes, drops the id, or leaks a vin)', async () => {
    const transaction = {
      id: 9, date: '2026-01-15', amount: 3.25, location: 'Old Rd', toll_tag_id: null, notes: 'x',
    } as unknown as TollTransaction
    const user = userEvent.setup()
    render(<TollTransactionForm vin="V1" tollTags={[]} transaction={transaction} onClose={vi.fn()} onSuccess={vi.fn()} />)
    await user.clear(screen.getByLabelText('toll.location *'))
    await user.type(screen.getByLabelText('toll.location *'), 'New Rd')
    await user.click(screen.getByRole('button', { name: 'toll.updateTransaction' }))
    await waitFor(() => expect(updateMutateAsync).toHaveBeenCalledTimes(1))
    // COMPLETE 6-property update object (id + all 5 body fields, NO vin). The seeded amount 3.25
    // round-trips through Number(...) → the number 3.25; the untouched toll_tag_id (seeded null) coerces to
    // undefined via the B2 valueAsNumber fix and posts as null. B3: toStrictEqual + toHaveProperty so a
    // dropped key fails.
    const payload = updateMutateAsync.mock.calls[0][0]
    expect(payload).toStrictEqual({
      id: 9,
      transaction_date: '2026-01-15',
      amount: 3.25,
      location: 'New Rd',
      toll_tag_id: null,
      notes: 'x',
    })
    expect(payload).toHaveProperty('toll_tag_id')
    expect(createMutateAsync).not.toHaveBeenCalled()
  })

  it('edit: picking "None (manual payment)" on a tagged transaction sends null, which unlinks the tag', async () => {
    const transaction = {
      id: 10, date: '2026-01-16', amount: 2, location: 'Tagged Rd', toll_tag_id: 7, notes: '',
    } as unknown as TollTransaction
    const user = userEvent.setup()
    render(<TollTransactionForm vin="V1" tollTags={[activeTag]} transaction={transaction} onClose={vi.fn()} onSuccess={vi.fn()} />)
    await user.selectOptions(screen.getByLabelText('toll.tollTag'), '')
    await user.click(screen.getByRole('button', { name: 'toll.updateTransaction' }))
    await waitFor(() => expect(updateMutateAsync).toHaveBeenCalledTimes(1))
    // Not undefined: the update route skips keys that aren't sent, so the tag stayed linked.
    expect(updateMutateAsync.mock.calls[0][0]).toHaveProperty('toll_tag_id', null)
  })

  it('the Field labels resolve to the controls carrying the expected ids (fails if a Field htmlFor/id association is dropped — including the currency carve-out)', () => {
    render(<TollTransactionForm vin="V1" tollTags={[]} onClose={vi.fn()} onSuccess={vi.fn()} />)
    expect(screen.getByLabelText('common:amount *')).toHaveAttribute('id', 'amount')
    expect(screen.getByLabelText('toll.location *')).toHaveAttribute('id', 'location')
  })
})

describe('TollTransactionForm — amount field on NumberInput, toll_tag_id stays a Select (Task 8)', () => {
  it('amount is a textbox and accepts a comma decimal; toll_tag_id stays a combobox', async () => {
    const user = userEvent.setup()
    render(<TollTransactionForm vin="V1" tollTags={[activeTag]} onClose={vi.fn()} onSuccess={vi.fn()} />)

    const amountInput = screen.getByLabelText('common:amount *')
    expect(amountInput).toHaveAttribute('type', 'text')
    expect(screen.getByRole('textbox', { name: 'common:amount *' })).toBe(amountInput)
    expect(screen.getByLabelText('toll.tollTag').tagName).toBe('SELECT')

    await user.clear(screen.getByLabelText('common:date *'))
    await user.type(screen.getByLabelText('common:date *'), '2026-02-01')
    await user.type(amountInput, '4,50')
    await user.clear(screen.getByLabelText('toll.location *'))
    await user.type(screen.getByLabelText('toll.location *'), 'Main St Toll')
    await user.selectOptions(screen.getByLabelText('toll.tollTag'), '7')
    await user.click(screen.getByRole('button', { name: 'toll.addTransaction' }))

    await waitFor(() => expect(createMutateAsync).toHaveBeenCalledTimes(1))
    const payload = createMutateAsync.mock.calls[0][0]
    expect(payload.amount).toBe(4.5)
    expect(payload.toll_tag_id).toBe(7)
  })

  it('rejects unparseable text in amount without crashing, and never calls create', async () => {
    const user = userEvent.setup()
    render(<TollTransactionForm vin="V1" tollTags={[]} onClose={vi.fn()} onSuccess={vi.fn()} />)

    await user.clear(screen.getByLabelText('common:date *'))
    await user.type(screen.getByLabelText('common:date *'), '2026-02-01')
    await user.type(screen.getByLabelText('common:amount *'), 'abc')
    await user.clear(screen.getByLabelText('toll.location *'))
    await user.type(screen.getByLabelText('toll.location *'), 'Main St Toll')
    await user.click(screen.getByRole('button', { name: 'toll.addTransaction' }))

    await waitFor(() =>
      expect(screen.getByText('common:validation.amount.invalid')).toBeInTheDocument()
    )
    expect(createMutateAsync).not.toHaveBeenCalled()
  })
})

describe('TollTransactionForm: the amount is required', () => {
  const stored = {
    id: 5, vin: 'V1', date: '2026-02-01', amount: '4.50', location: 'Main St Toll',
    toll_tag_id: null, notes: null, created_at: '2026-02-01T00:00:00',
  } as unknown as TollTransaction

  it('clearing it on edit blocks the save with an inline error instead of keeping the old amount', async () => {
    const user = userEvent.setup()
    render(<TollTransactionForm vin="V1" tollTags={[]} transaction={stored} onClose={vi.fn()} onSuccess={vi.fn()} />)
    await user.clear(screen.getByLabelText('common:amount *'))
    await user.click(screen.getByRole('button', { name: 'toll.updateTransaction' }))
    expect(await screen.findByText('common:validation.amount.required')).toBeInTheDocument()
    expect(updateMutateAsync).not.toHaveBeenCalled()
  })

  it('leaving it empty on create blocks the save inline', async () => {
    const user = userEvent.setup()
    render(<TollTransactionForm vin="V1" tollTags={[]} onClose={vi.fn()} onSuccess={vi.fn()} />)
    await user.type(screen.getByLabelText('toll.location *'), 'Main St Toll')
    await user.click(screen.getByRole('button', { name: 'toll.addTransaction' }))
    expect(await screen.findByText('common:validation.amount.required')).toBeInTheDocument()
    expect(createMutateAsync).not.toHaveBeenCalled()
  })
})

describe('TollTransactionForm: a rejected save', () => {
  const tollForm = (): HTMLFormElement => document.getElementById('toll-transaction-form') as HTMLFormElement
  const banner = (): HTMLElement | null => screen.queryByText(/^Failed to toll\.saveTransactionAction\./)
  const openFilled = (): void => {
    render(<TollTransactionForm vin="V1" tollTags={[activeTag]} onClose={vi.fn()} onSuccess={vi.fn()} />)
    fireEvent.change(document.getElementById('transaction_date')!, { target: { value: '2026-02-01' } })
    fireEvent.change(document.getElementById('amount')!, { target: { value: '4.50' } })
    fireEvent.change(document.getElementById('location')!, { target: { value: 'Main St Toll' } })
  }

  it('a non-422 failure shows the banner and no field error', async () => {
    createMutateAsync.mockRejectedValueOnce(new Error('Network Error'))
    openFilled()
    await submitAndSettle(tollForm())

    expect(screen.getByText('Failed to toll.saveTransactionAction. Network Error')).toBeInTheDocument()
    expect(document.getElementById('location-error')).toBeNull()
  })

  it('a 422 on location shows under location and no banner', async () => {
    createMutateAsync.mockRejectedValueOnce(validationError({ location: 'String should have at most 200 characters' }))
    openFilled()
    await submitAndSettle(tollForm())

    expect(document.getElementById('location-error')).toHaveTextContent('String should have at most 200 characters')
    expect(banner()).toBeNull()
  })

  // Named controls that aren't payload fields go here. None today.
  const UI_ONLY: string[] = []

  // Guard for knownFields drift and silent fields: a 422 on any field the form
  // registers has to show under that field. Mutant: drop a name from
  // knownFields and it banners.
  it('guard: a 422 on each field shows under it', async () => {
    openFilled()
    const names = registeredFieldNames(tollForm(), UI_ONLY)
    // An empty sweep would pass, so pin the names it must contain.
    expect(names).toEqual(expect.arrayContaining(['transaction_date', 'amount', 'location', 'toll_tag_id', 'notes']))

    const wrong: string[] = []
    for (const name of names) {
      const got = await whereA422Lands(tollForm(), createMutateAsync, name, `bad ${name}`, banner)
      if (got !== 'field') wrong.push(`${name}: ${got}`)
    }
    expect(wrong).toEqual([])
  })
})
