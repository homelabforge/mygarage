import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { render } from '../../../__tests__/test-utils'
import type { InsurancePolicy } from '../../../types/insurance'

const attach = vi.fn().mockResolvedValue({})
vi.mock('../../../hooks/queries/useInsuranceRecords', () => ({
  useAttachPolicyVehicle: () => ({ mutateAsync: attach, isPending: false }),
}))
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }))
// #211: the country profile orders the formulas and names the no-claims field.
const profileState: {
  policyTypes: string[]
  noClaims: { scheme: string; name: string; pattern: string; example: string } | null
} = { policyTypes: [], noClaims: null }
vi.mock('../../../hooks/useInsuranceProfile', () => ({
  useInsuranceProfile: () => ({ country: null, coverageKeys: [], ...profileState }),
}))

import AddToPolicyDialog from '../AddToPolicyDialog'

const policy = { id: 3, provider: 'State Farm', policy_number: 'P-1' } as InsurancePolicy

function renderDialog(): void {
  render(<AddToPolicyDialog vin="V1" policies={[policy]} onClose={vi.fn()} onSuccess={vi.fn()} />)
  fireEvent.change(document.getElementById('attach_type') as HTMLSelectElement, { target: { value: 'Liability' } })
}

const add = (): void => {
  fireEvent.click(screen.getByRole('button', { name: 'common:add' }))
}

beforeEach(() => vi.clearAllMocks())

// money-fits: the API takes a premium share from 0 to MONEY_MAX
// (9,999,999,999.99). Past it the attach came back a 422 toast.
describe('AddToPolicyDialog: the premium share', () => {
  it.each([
    ['10000000000', 'common:validation.amount.tooLarge'],
    ['-5', 'common:validation.amount.negative'],
    ['abc', 'common:validation.amount.invalid'],
  ])('refuses %s on the field and sends nothing', async (typed, message) => {
    renderDialog()
    fireEvent.change(screen.getByLabelText(/insurance\.vehicleShare/), { target: { value: typed } })
    add()

    expect(await screen.findByText(message)).toBeInTheDocument()
    expect(attach).not.toHaveBeenCalled()
  })

  it('the share error clears when the share is edited', async () => {
    renderDialog()
    const share = screen.getByLabelText(/insurance\.vehicleShare/)
    fireEvent.change(share, { target: { value: '-5' } })
    add()
    expect(await screen.findByText('common:validation.amount.negative')).toBeInTheDocument()

    fireEvent.change(share, { target: { value: '120' } })
    expect(screen.queryByText('common:validation.amount.negative')).not.toBeInTheDocument()
    expect(share).not.toHaveAttribute('aria-invalid')
    expect(attach).not.toHaveBeenCalled()
  })

  it('sends MONEY_MAX itself, and a blank share as null', async () => {
    renderDialog()
    fireEvent.change(screen.getByLabelText(/insurance\.vehicleShare/), { target: { value: '9999999999.99' } })
    add()
    await waitFor(() => expect(attach).toHaveBeenCalledTimes(1))
    expect(attach.mock.calls[0][0]).toMatchObject({ policyId: 3, vin: 'V1', premium_share: 9999999999.99 })

    fireEvent.change(screen.getByLabelText(/insurance\.vehicleShare/), { target: { value: '' } })
    add()
    await waitFor(() => expect(attach).toHaveBeenCalledTimes(2))
    expect(attach.mock.calls[1][0].premium_share).toBeNull()
  })
})

describe('AddToPolicyDialog — Europe (#211)', () => {
  beforeEach(() => {
    profileState.policyTypes = ['Third Party', 'Third Party Extended', 'Full Coverage', 'Other']
    profileState.noClaims = { scheme: 'crm', name: 'Bonus-malus (CRM)', pattern: '^[0-3][.,][0-9]{2}$', example: '0.50' }
  })
  afterEach(() => {
    profileState.policyTypes = []
    profileState.noClaims = null
  })

  it('offers the profile’s formulas first and sends the no-claims class with the link', async () => {
    renderDialog()
    const options = Array.from((document.getElementById('attach_type') as HTMLSelectElement).options)
      .map((option) => option.value)
      .filter(Boolean)
    expect(options.slice(0, 4)).toEqual(['Third Party', 'Third Party Extended', 'Full Coverage', 'Other'])
    expect(options).toContain('Liability')
    fireEvent.change(document.getElementById('attach_type') as HTMLSelectElement, { target: { value: 'Third Party' } })
    const noClaims = screen.getByLabelText('Bonus-malus (CRM)') as HTMLInputElement
    expect(noClaims.placeholder).toBe('0.50')
    fireEvent.change(noClaims, { target: { value: '0.50' } })
    add()
    await waitFor(() => expect(attach).toHaveBeenCalledTimes(1))
    expect(attach.mock.calls[0][0]).toMatchObject({ policy_type: 'Third Party', no_claims_class: '0.50' })
  })

  it('refuses a class the API would refuse before sending it', () => {
    renderDialog()
    fireEvent.change(screen.getByLabelText('Bonus-malus (CRM)'), { target: { value: 'far too long a class' } })
    expect(screen.getByText('insurance.noClaimsClassInvalid')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'common:add' })).toBeDisabled()
    expect(attach).not.toHaveBeenCalled()
  })

  it('without a no-claims scheme in the profile there is no class field, and null is sent', async () => {
    profileState.noClaims = null
    renderDialog()
    expect(screen.queryByLabelText('Bonus-malus (CRM)')).not.toBeInTheDocument()
    add()
    await waitFor(() => expect(attach).toHaveBeenCalledTimes(1))
    expect(attach.mock.calls[0][0]).toMatchObject({ no_claims_class: null })
  })
})
