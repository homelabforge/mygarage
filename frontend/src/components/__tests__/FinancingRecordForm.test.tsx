import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { render } from '../../__tests__/test-utils'
import { validationError } from '../../__tests__/serverErrors'
import type { FinancingRecord } from '../../types/financing'

const createMutateAsync = vi.fn().mockResolvedValue({})
const updateMutateAsync = vi.fn().mockResolvedValue({})
vi.mock('../../hooks/queries/useFinancingRecords', () => ({
  useCreateFinancingRecord: () => ({ mutateAsync: createMutateAsync }),
  useUpdateFinancingRecord: () => ({ mutateAsync: updateMutateAsync }),
}))
vi.mock('../../hooks/useCurrencyPreference', () => ({ useCurrencyPreference: () => ({ currencyCode: 'USD', locale: 'en-US', formatCurrency: vi.fn() }) }))
// VendorSearch fetches vendors; stub it with a clear affordance so tests can
// simulate the user removing the selected lender (VendorSearch calls onSelect(null) on clear).
vi.mock('../VendorSearch', () => ({
  default: ({ onSelect }: { onSelect: (vendor: null) => void }) => (
    <div data-testid="vendor-search">
      <button type="button" onClick={() => onSelect(null)}>
        clear-vendor
      </button>
    </div>
  ),
}))

import FinancingRecordForm from '../FinancingRecordForm'

beforeEach(() => vi.clearAllMocks())

describe('FinancingRecordForm — routing + exact payload (SDQ-C)', () => {
  it('create submits the COMPLETE payload INCLUDING vin (amount coerced to a number), and NEVER calls update (fails if a field is dropped, vin is omitted, the amount stays a string, or it misroutes)', async () => {
    const user = userEvent.setup()
    render(<FinancingRecordForm vin="V1" onClose={vi.fn()} onSuccess={vi.fn()} />)
    await user.clear(screen.getByLabelText('financing.date *'))
    await user.type(screen.getByLabelText('financing.date *'), '2026-03-01')
    await user.selectOptions(screen.getByLabelText('financing.category *'), 'lease_payment')
    await user.clear(screen.getByLabelText('common:amount *'))
    await user.type(screen.getByLabelText('common:amount *'), '450.00')
    await user.clear(screen.getByLabelText('common:notes'))
    await user.type(screen.getByLabelText('common:notes'), 'note')
    await user.click(screen.getByRole('button', { name: 'common:create' }))
    await waitFor(() => expect(createMutateAsync).toHaveBeenCalledTimes(1))
    const payload = createMutateAsync.mock.calls[0][0]
    expect(payload).toStrictEqual({
      vin: 'V1',
      date: '2026-03-01',
      category: 'lease_payment',
      amount: 450,
      vendor_id: null,
      notes: 'note',
    })
    expect(payload).toHaveProperty('vin')
    expect(updateMutateAsync).not.toHaveBeenCalled()
  })

  it('edit submits the UPDATE payload — routing id + vin + edited amount — and NEVER calls create (fails if it misroutes or drops the id/vin)', async () => {
    const record = {
      id: 6, date: '2026-01-10', category: 'loan_payment', amount: 300, vendor_id: 9, notes: 'y',
    } as unknown as FinancingRecord
    const user = userEvent.setup()
    render(<FinancingRecordForm vin="V1" record={record} onClose={vi.fn()} onSuccess={vi.fn()} />)
    await user.clear(screen.getByLabelText('common:amount *'))
    await user.type(screen.getByLabelText('common:amount *'), '325.50')
    await user.click(screen.getByRole('button', { name: 'common:update' }))
    await waitFor(() => expect(updateMutateAsync).toHaveBeenCalledTimes(1))
    const payload = updateMutateAsync.mock.calls[0][0]
    expect(payload).toStrictEqual({
      id: 6,
      vin: 'V1',
      date: '2026-01-10',
      category: 'loan_payment',
      amount: 325.5,
      vendor_id: 9,
      notes: 'y',
    })
    expect(payload).toHaveProperty('vin')
    expect(createMutateAsync).not.toHaveBeenCalled()
  })

  it('clearing the lender on edit sends vendor_id: null, not undefined/omitted (fails if the payload drops the field instead of explicitly clearing it)', async () => {
    const record = {
      id: 6, date: '2026-01-10', category: 'loan_payment', amount: 300, vendor_id: 9, notes: 'y',
    } as unknown as FinancingRecord
    const user = userEvent.setup()
    render(<FinancingRecordForm vin="V1" record={record} onClose={vi.fn()} onSuccess={vi.fn()} />)
    await user.click(screen.getByRole('button', { name: 'clear-vendor' }))
    await user.click(screen.getByRole('button', { name: 'common:update' }))
    await waitFor(() => expect(updateMutateAsync).toHaveBeenCalledTimes(1))
    const payload = updateMutateAsync.mock.calls[0][0]
    expect(payload).toMatchObject({ id: 6, vin: 'V1', vendor_id: null })
    expect(payload).toHaveProperty('vendor_id', null)
  })

  it('the Field labels resolve to the controls carrying the expected ids (fails if a Field htmlFor/id association is dropped — including the currency carve-out)', () => {
    render(<FinancingRecordForm vin="V1" onClose={vi.fn()} onSuccess={vi.fn()} />)
    expect(screen.getByLabelText('common:amount *')).toHaveAttribute('id', 'amount')
    expect(screen.getByLabelText('financing.date *')).toHaveAttribute('id', 'date')
    expect(screen.getByLabelText('financing.category *')).toHaveAttribute('id', 'category')
  })

  it('labels the vendor picker "Lender", not "Vendor" (fails if the relabel regresses)', () => {
    render(<FinancingRecordForm vin="V1" onClose={vi.fn()} onSuccess={vi.fn()} />)
    expect(screen.getByText('financing.lender')).toBeInTheDocument()
  })
})

describe('FinancingRecordForm — required category', () => {
  it('rejects submission with no category selected (fails if category is left optional)', async () => {
    const user = userEvent.setup()
    render(<FinancingRecordForm vin="V1" onClose={vi.fn()} onSuccess={vi.fn()} />)
    await user.clear(screen.getByLabelText('financing.date *'))
    await user.type(screen.getByLabelText('financing.date *'), '2026-03-01')
    await user.clear(screen.getByLabelText('common:amount *'))
    await user.type(screen.getByLabelText('common:amount *'), '100')
    await user.click(screen.getByRole('button', { name: 'common:create' }))

    await waitFor(() =>
      expect(screen.getByText('common:validation.financing.categoryRequired')).toBeInTheDocument()
    )
    expect(createMutateAsync).not.toHaveBeenCalled()
  })
})

describe('FinancingRecordForm — amount field on NumberInput (Task 8 convention)', () => {
  it('is a textbox, not a spinbutton, and accepts a comma decimal', async () => {
    const user = userEvent.setup()
    render(<FinancingRecordForm vin="V1" onClose={vi.fn()} onSuccess={vi.fn()} />)
    const amountInput = screen.getByLabelText('common:amount *')
    expect(amountInput).toHaveAttribute('type', 'text')
    expect(screen.getByRole('textbox', { name: 'common:amount *' })).toBe(amountInput)

    await user.clear(screen.getByLabelText('financing.date *'))
    await user.type(screen.getByLabelText('financing.date *'), '2026-03-01')
    await user.selectOptions(screen.getByLabelText('financing.category *'), 'lease_payment')
    await user.type(amountInput, '450,00')
    await user.click(screen.getByRole('button', { name: 'common:create' }))

    await waitFor(() => expect(createMutateAsync).toHaveBeenCalledTimes(1))
    expect(createMutateAsync.mock.calls[0][0]).toMatchObject({ amount: 450 })
  })

  it('rejects unparseable text instead of silently discarding it', async () => {
    const user = userEvent.setup()
    render(<FinancingRecordForm vin="V1" onClose={vi.fn()} onSuccess={vi.fn()} />)
    await user.clear(screen.getByLabelText('financing.date *'))
    await user.type(screen.getByLabelText('financing.date *'), '2026-03-01')
    await user.selectOptions(screen.getByLabelText('financing.category *'), 'lease_payment')
    await user.type(screen.getByLabelText('common:amount *'), 'abc')
    await user.click(screen.getByRole('button', { name: 'common:create' }))

    await waitFor(() =>
      expect(screen.getByText('common:validation.amount.invalid')).toBeInTheDocument()
    )
    expect(createMutateAsync).not.toHaveBeenCalled()
  })
})

describe('FinancingRecordForm: a rejected save', () => {
  const banner = (): HTMLElement | null => screen.queryByText(/^Failed to financing\.saveAction\./)
  const fillAndCreate = async (user: ReturnType<typeof userEvent.setup>): Promise<void> => {
    await user.clear(screen.getByLabelText('financing.date *'))
    await user.type(screen.getByLabelText('financing.date *'), '2026-03-01')
    await user.selectOptions(screen.getByLabelText('financing.category *'), 'lease_payment')
    await user.type(screen.getByLabelText('common:amount *'), '450')
    await user.click(screen.getByRole('button', { name: 'common:create' }))
  }

  it('a non-422 failure shows the banner and no field error', async () => {
    createMutateAsync.mockRejectedValueOnce(new Error('Network Error'))
    const user = userEvent.setup()
    render(<FinancingRecordForm vin="V1" onClose={vi.fn()} onSuccess={vi.fn()} />)
    await fillAndCreate(user)

    expect(await screen.findByText('Failed to financing.saveAction. Network Error')).toBeInTheDocument()
    expect(document.getElementById('amount-error')).toBeNull()
  })

  it('a 422 on amount shows under amount and no banner', async () => {
    createMutateAsync.mockRejectedValueOnce(validationError({ amount: 'Input should be greater than 0' }))
    const user = userEvent.setup()
    render(<FinancingRecordForm vin="V1" onClose={vi.fn()} onSuccess={vi.fn()} />)
    await fillAndCreate(user)

    await waitFor(() => expect(document.getElementById('amount-error')).not.toBeNull())
    expect(document.getElementById('amount-error')).toHaveTextContent('Input should be greater than 0')
    expect(banner()).toBeNull()
  })
})
