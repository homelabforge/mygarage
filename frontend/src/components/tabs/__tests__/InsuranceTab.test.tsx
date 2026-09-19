import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { render } from '../../../__tests__/test-utils'
import type { InsurancePolicy } from '../../../types/insurance'

const VIN = 'MIRAGEVIN00000002'

const make = (id: number, status: InsurancePolicy['status'], vins: string[], can_edit = true) =>
  ({
    id,
    provider: `Insurer ${id}`,
    policy_number: `P-${id}`,
    start_date: '2026-01-01',
    end_date: '2026-07-01',
    premium_amount: null,
    premium_frequency: null,
    notes: null,
    status,
    previous_policy_id: null,
    has_successor: false,
    fields: [],
    vehicles: vins.map((vin, index) => ({
      id: id * 10 + index, vin, vehicle_name: vin, policy_type: 'Liability', fields: [], can_edit: true,
    })),
    other_vehicle_count: 0,
    can_edit,
  }) as unknown as InsurancePolicy

let vehiclePolicies: InsurancePolicy[] = []
let householdPolicies: InsurancePolicy[] = []
vi.mock('../../../hooks/queries/useInsuranceRecords', () => ({
  useInsuranceRecords: () => ({ data: vehiclePolicies, isLoading: false, error: null }),
  useInsurancePolicies: () => ({ data: householdPolicies }),
  useDeleteInsurancePolicy: () => ({ mutate: vi.fn(), isPending: false }),
  useAttachPolicyVehicle: () => ({ mutateAsync: vi.fn(), isPending: false }),
}))
vi.mock('../../../hooks/useCurrencyPreference', () => ({
  useCurrencyPreference: () => ({ currencyCode: 'USD', locale: 'en-US', formatCurrency: vi.fn() }),
}))
vi.mock('../../../hooks/useDateLocale', () => ({ useDateLocale: () => undefined }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import InsuranceTab from '../InsuranceTab'

beforeEach(() => {
  vehiclePolicies = []
  householdPolicies = []
})

describe('InsuranceTab', () => {
  it('hides past policies until asked, so the current cover is what you see', async () => {
    const user = userEvent.setup()
    vehiclePolicies = [make(1, 'active', [VIN]), make(2, 'expired', [VIN])]
    render(<InsuranceTab vin={VIN} />)

    expect(screen.getByRole('heading', { name: 'Insurer 1' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Insurer 2' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'insurancePolicies.showHistory' }))
    expect(screen.getByRole('heading', { name: 'Insurer 2' })).toBeInTheDocument()
  })

  it('offers "add to existing policy" only for editable household policies this vehicle is not on', () => {
    vehiclePolicies = [make(1, 'active', [VIN])]
    householdPolicies = [
      make(1, 'active', [VIN]), // already covers it
      make(3, 'active', ['RAMVIN00000000001'], false), // not editable by this user
    ]
    const { unmount } = render(<InsuranceTab vin={VIN} />)
    expect(
      screen.queryByRole('button', { name: 'insurancePolicies.addToExisting' })
    ).not.toBeInTheDocument()
    unmount()

    householdPolicies = [make(4, 'active', ['RAMVIN00000000001'])]
    render(<InsuranceTab vin={VIN} />)
    expect(screen.getByRole('button', { name: 'insurancePolicies.addToExisting' })).toBeInTheDocument()
  })
})
