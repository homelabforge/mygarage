import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import { render } from '../../../__tests__/test-utils'
import { answerConfirm } from '../../../__tests__/confirmHelpers'

// Delete asks through the app confirm first; only a yes runs the mutation.

vi.mock('../../../hooks/useCurrencyPreference', () => ({
  useCurrencyPreference: () => ({ currencyCode: 'USD', locale: 'en-US', formatCurrency: vi.fn() }),
}))
vi.mock('../../../hooks/useDateLocale', () => ({ useDateLocale: () => undefined }))
vi.mock('../../../hooks/useInsuranceProfile', () => ({
  useInsuranceProfile: () => ({ country: null, policyTypes: [], coverageKeys: [], noClaims: null }),
}))
const deleteMutate = vi.fn()
vi.mock('../../../hooks/queries/useInsuranceRecords', () => ({
  useDeleteInsurancePolicy: () => ({ mutate: deleteMutate, isPending: false, variables: undefined }),
}))

import PolicyBoard from '../PolicyBoard'
import type { InsurancePolicy } from '../../../types/insurance'

const POLICY: InsurancePolicy = {
  id: 7,
  provider: 'Progressive',
  policy_number: 'P-100',
  start_date: '2026-01-01',
  end_date: '2026-07-01',
  premium_amount: '600.00',
  premium_frequency: 'Semi-Annual',
  notes: null,
  status: 'active',
  previous_policy_id: null,
  has_successor: false,
  created_by_user_id: 1,
  created_at: null,
  fields: [],
  vehicles: [
    {
      id: 1,
      vin: 'RAMVIN00000000001',
      vehicle_name: 'Ram',
      policy_type: 'Full Coverage',
      premium_share: null,
      effective_share: '600.00',
      deductible: null,
      notes: null,
      coverages: [],
      effective_to: null,
      fields: [],
      can_edit: true,
    },
  ],
  other_vehicle_count: 0,
  can_edit: true,
}

beforeEach(() => {
  deleteMutate.mockReset()
})

describe('PolicyBoard delete', () => {
  it('a confirmed delete deletes that policy', async () => {
    render(<PolicyBoard policies={[POLICY]} isLoading={false} error={null} />)
    fireEvent.click(screen.getByRole('button', { name: 'common:delete' }))
    await answerConfirm('confirm', 'insuranceList.confirmDelete')
    expect(deleteMutate).toHaveBeenCalledTimes(1)
    expect(deleteMutate.mock.calls[0][0]).toBe(7)
  })

  it('a cancelled delete deletes nothing', async () => {
    render(<PolicyBoard policies={[POLICY]} isLoading={false} error={null} />)
    fireEvent.click(screen.getByRole('button', { name: 'common:delete' }))
    await answerConfirm('cancel', 'insuranceList.confirmDelete')
    expect(deleteMutate).not.toHaveBeenCalled()
  })
})
