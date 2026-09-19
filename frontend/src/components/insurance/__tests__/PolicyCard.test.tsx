import { describe, it, expect, vi } from 'vitest'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { render } from '../../../__tests__/test-utils'

vi.mock('../../../hooks/useCurrencyPreference', () => ({
  useCurrencyPreference: () => ({ currencyCode: 'USD', locale: 'en-US', formatCurrency: vi.fn() }),
}))
vi.mock('../../../hooks/useDateLocale', () => ({ useDateLocale: () => undefined }))

import PolicyCard from '../PolicyCard'
import type { InsurancePolicy, PolicyVehicle } from '../../../types/insurance'

const vehicle = (over: Partial<PolicyVehicle>): PolicyVehicle => ({
  id: 1,
  vin: 'RAMVIN00000000001',
  vehicle_name: 'Ram',
  policy_type: 'Full Coverage',
  premium_share: null,
  effective_share: '320.00',
  deductible: '500.00',
  coverage_limits: null,
  notes: null,
  effective_to: null,
  fields: [{ label: 'Collision Deductible', value: '$500' }],
  can_edit: true,
  ...over,
})

const policy = (over: Partial<InsurancePolicy> = {}): InsurancePolicy => ({
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
  fields: [{ label: 'Agent Phone', value: '555-0100' }],
  vehicles: [
    vehicle({}),
    vehicle({ id: 2, vin: 'MIRAGEVIN00000002', vehicle_name: 'Mirage', policy_type: 'Liability', effective_share: '280.00', deductible: null, fields: [] }),
  ],
  other_vehicle_count: 0,
  can_edit: true,
  ...over,
})

const handlers = () => ({
  onEdit: vi.fn(),
  onRenew: vi.fn(),
  onReplace: vi.fn(),
  onHistory: vi.fn(),
  onDelete: vi.fn(),
})

describe('PolicyCard', () => {
  it('shows the policy ONCE with every covered vehicle listed beneath it, each with its own coverage', () => {
    render(<PolicyCard policy={policy()} {...handlers()} />)

    expect(screen.getAllByRole('heading', { name: 'Progressive' })).toHaveLength(1)
    const covered = screen.getByRole('region', { name: 'insurancePolicies.coveredVehicles' })
    const rows = within(covered).getAllByRole('listitem')
    expect(rows).toHaveLength(2)
    expect(within(rows[0]).getByText('Ram')).toBeInTheDocument()
    expect(within(rows[0]).getByText('Full Coverage')).toBeInTheDocument()
    expect(within(rows[0]).getByText('Collision Deductible')).toBeInTheDocument()
    expect(within(rows[1]).getByText('Mirage')).toBeInTheDocument()
    expect(within(rows[1]).getByText('Liability')).toBeInTheDocument()
    // The policy-level named field sits with the policy, not inside a vehicle.
    expect(within(covered).queryByText('Agent Phone')).not.toBeInTheDocument()
    expect(screen.getByText('Agent Phone')).toBeInTheDocument()
  })

  it("on a vehicle's tab shows THAT vehicle in full and only names the others", () => {
    render(<PolicyCard policy={policy()} focusVin="MIRAGEVIN00000002" {...handlers()} />)

    const covered = screen.getByRole('region', { name: 'insurancePolicies.coveredVehicles' })
    const rows = within(covered).getAllByRole('listitem')
    expect(rows).toHaveLength(1)
    expect(within(rows[0]).getByText('Mirage')).toBeInTheDocument()
    expect(within(covered).getByText('insurancePolicies.alsoCovers')).toBeInTheDocument()
  })

  it('reduces vehicles the caller cannot see to a count', () => {
    render(<PolicyCard policy={policy({ other_vehicle_count: 2 })} {...handlers()} />)
    expect(screen.getByText('insurancePolicies.otherVehicles')).toBeInTheDocument()
  })

  it('offers Renew and Switch insurer only to someone who can edit a policy with no successor yet', async () => {
    const user = userEvent.setup()
    const h = handlers()
    const { rerender } = render(<PolicyCard policy={policy()} {...h} />)
    await user.click(screen.getByRole('button', { name: 'insurancePolicies.renew' }))
    await user.click(screen.getByRole('button', { name: 'insurancePolicies.switchInsurer' }))
    expect(h.onRenew).toHaveBeenCalledTimes(1)
    expect(h.onReplace).toHaveBeenCalledTimes(1)

    rerender(<PolicyCard policy={policy({ has_successor: true })} {...h} />)
    expect(screen.queryByRole('button', { name: 'insurancePolicies.renew' })).not.toBeInTheDocument()
    expect(screen.getByText('insurancePolicies.alreadyRenewed')).toBeInTheDocument()
    // A renewed policy has a chain worth reviewing.
    expect(screen.getByRole('button', { name: 'insurancePolicies.viewHistory' })).toBeInTheDocument()

    rerender(<PolicyCard policy={policy({ can_edit: false })} {...h} />)
    expect(screen.queryByRole('button', { name: 'insurancePolicies.renew' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'common:edit' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'common:delete' })).not.toBeInTheDocument()
  })

  it('labels the status', () => {
    const { rerender } = render(<PolicyCard policy={policy({ status: 'upcoming' })} {...handlers()} />)
    expect(screen.getByText('vehicles:insurancePolicies.statusUpcoming')).toBeInTheDocument()
    rerender(<PolicyCard policy={policy({ status: 'expired' })} {...handlers()} />)
    expect(screen.getByText('vehicles:insurancePolicies.statusExpired')).toBeInTheDocument()
  })
})
