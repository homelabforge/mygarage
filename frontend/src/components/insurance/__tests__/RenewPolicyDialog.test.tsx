import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { render } from '../../../__tests__/test-utils'
import type { InsurancePolicy } from '../../../types/insurance'

const renewMutateAsync = vi.fn().mockResolvedValue({})
vi.mock('../../../hooks/queries/useInsuranceRecords', () => ({
  useRenewInsurancePolicy: () => ({ mutateAsync: renewMutateAsync }),
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import RenewPolicyDialog from '../RenewPolicyDialog'

beforeEach(() => vi.clearAllMocks())

const policy = {
  id: 7,
  provider: 'Progressive',
  policy_number: 'P-100',
  start_date: '2026-01-01',
  end_date: '2026-07-01',
  premium_amount: '600.00',
  premium_frequency: 'Semi-Annual',
} as InsurancePolicy

describe('RenewPolicyDialog', () => {
  it('defaults to the next term: starting where this one ends, the same length', () => {
    render(<RenewPolicyDialog policy={policy} onClose={vi.fn()} onSuccess={vi.fn()} />)
    expect(screen.getByLabelText('common:startDate *')).toHaveValue('2026-07-01')
    // 181 days after 2026-07-01, the length of the term being renewed.
    expect(screen.getByLabelText('common:endDate *')).toHaveValue('2026-12-29')
    expect(screen.getByLabelText('insurance.newPremium')).toHaveValue('600')
  })

  it('sends only what a renewal notice changes: the premium and the dates', async () => {
    const user = userEvent.setup()
    const onSuccess = vi.fn()
    render(<RenewPolicyDialog policy={policy} onClose={vi.fn()} onSuccess={onSuccess} />)
    const premium = screen.getByLabelText('insurance.newPremium')
    await user.clear(premium)
    await user.type(premium, '684')
    await user.click(screen.getByRole('button', { name: 'insurance.renewConfirm' }))

    await waitFor(() => expect(renewMutateAsync).toHaveBeenCalledTimes(1))
    expect(renewMutateAsync).toHaveBeenCalledWith({
      id: 7,
      start_date: '2026-07-01',
      end_date: '2026-12-29',
      premium_amount: 684,
    })
    expect(onSuccess).toHaveBeenCalled()
  })

  it('refuses an end date before the start', async () => {
    const user = userEvent.setup()
    render(<RenewPolicyDialog policy={policy} onClose={vi.fn()} onSuccess={vi.fn()} />)
    const end = screen.getByLabelText('common:endDate *')
    await user.clear(end)
    await user.type(end, '2026-06-01')
    await user.click(screen.getByRole('button', { name: 'insurance.renewConfirm' }))

    expect(await screen.findByText('forms:insurance.endBeforeStart')).toBeInTheDocument()
    expect(renewMutateAsync).not.toHaveBeenCalled()
  })
})
