import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { toast } from 'sonner'
import { render } from '../../../__tests__/test-utils'
import type { InsurancePDFParseResponse, InsurancePolicy } from '../../../types/insurance'

const createMutateAsync = vi.fn().mockResolvedValue({})
const updateMutateAsync = vi.fn().mockResolvedValue({})
const replaceMutateAsync = vi.fn().mockResolvedValue({})
vi.mock('../../../hooks/queries/useInsuranceRecords', () => ({
  useCreateInsurancePolicy: () => ({ mutateAsync: createMutateAsync }),
  useUpdateInsurancePolicy: () => ({ mutateAsync: updateMutateAsync }),
  useReplaceInsurancePolicy: () => ({ mutateAsync: replaceMutateAsync }),
}))
vi.mock('../../../hooks/queries/useQuickEntryVehicles', () => ({
  useQuickEntryVehicles: () => ({
    data: [
      { vin: 'RAMVIN00000000001', nickname: 'Ram', year: 2025, make: 'Ram', model: '3500', vehicle_type: 'Truck', thumbnail_url: null },
      { vin: 'MIRAGEVIN00000002', nickname: 'Mirage', year: 2017, make: 'Mitsubishi', model: 'Mirage', vehicle_type: 'Car', thumbnail_url: null },
    ],
  }),
}))
vi.mock('../../../hooks/useCurrencyPreference', () => ({
  useCurrencyPreference: () => ({ currencyCode: 'USD', locale: 'en-US', formatCurrency: vi.fn() }),
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

// The upload dialog is its own tested unit; here it is a button that hands
// back a canned parse, so the FORM's handling of that parse is what is tested.
let cannedParse: InsurancePDFParseResponse
vi.mock('../../InsurancePDFUpload', () => ({
  default: ({ onDataExtracted }: { onDataExtracted: (parsed: InsurancePDFParseResponse) => void }) => (
    <button type="button" onClick={() => onDataExtracted(cannedParse)}>
      fake-use-parse
    </button>
  ),
}))

import PolicyForm from '../PolicyForm'

beforeEach(() => vi.clearAllMocks())

const RAM = 'RAMVIN00000000001'
const MIRAGE = 'MIRAGEVIN00000002'

const fillPolicy = async (user: ReturnType<typeof userEvent.setup>, premium = '600') => {
  await user.type(screen.getByLabelText('insurance.provider *'), 'Progressive')
  await user.type(screen.getByLabelText('insurance.policyNumber *'), 'P-100')
  await user.type(screen.getByLabelText('common:startDate *'), '2026-01-01')
  await user.type(screen.getByLabelText('common:endDate *'), '2026-07-01')
  await user.type(screen.getByLabelText('insurance.policyPremium'), premium)
  await user.selectOptions(screen.getByLabelText('insurance.premiumFrequency'), 'Semi-Annual')
}

const addVehicle = async (user: ReturnType<typeof userEvent.setup>, vin: string, type: string, index: number) => {
  await user.selectOptions(screen.getByLabelText('insurance.addVehicle'), vin)
  await user.click(screen.getByRole('button', { name: 'common:add' }))
  await user.selectOptions(screen.getAllByLabelText('insurance.policyType *')[index], type)
}

const existing = (over: Partial<InsurancePolicy> = {}): InsurancePolicy => ({
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
    {
      id: 1, vin: RAM, vehicle_name: 'Ram', policy_type: 'Full Coverage', premium_share: '400.00',
      effective_share: '400.00', deductible: '500.00', notes: null, effective_to: null,
      coverages: [{ coverage_key: 'collision', deductible: '500.00' }],
      fields: [{ label: 'Lienholder', value: 'Ally' }], can_edit: true,
    },
    {
      id: 2, vin: MIRAGE, vehicle_name: 'Mirage', policy_type: 'Liability', premium_share: '200.00',
      effective_share: '200.00', deductible: null, notes: null,
      effective_to: null, coverages: [], fields: [], can_edit: true,
    },
  ],
  other_vehicle_count: 0,
  can_edit: true,
  ...over,
})

describe('PolicyForm — create', () => {
  it('submits the policy with every vehicle beneath it in ONE payload', async () => {
    const user = userEvent.setup()
    render(<PolicyForm mode="create" onClose={vi.fn()} onSuccess={vi.fn()} />)
    await fillPolicy(user)
    await addVehicle(user, RAM, 'Full Coverage', 0)
    await addVehicle(user, MIRAGE, 'Liability', 1)
    await user.type(screen.getAllByLabelText('insurance.vehicleShare')[0], '400')
    await user.type(screen.getAllByLabelText('insurance.deductible')[0], '500')

    await user.click(screen.getByRole('button', { name: 'common:create' }))

    await waitFor(() => expect(createMutateAsync).toHaveBeenCalledTimes(1))
    expect(createMutateAsync).toHaveBeenCalledWith({
      provider: 'Progressive',
      policy_number: 'P-100',
      start_date: '2026-01-01',
      end_date: '2026-07-01',
      premium_amount: 600,
      premium_frequency: 'Semi-Annual',
      notes: null,
      fields: [],
      vehicles: [
        { vin: RAM, policy_type: 'Full Coverage', premium_share: 400, deductible: 500, notes: null, coverages: [], fields: [] },
        // No share typed: null, so the backend splits what the Ram leaves.
        { vin: MIRAGE, policy_type: 'Liability', premium_share: null, deductible: null, notes: null, coverages: [], fields: [] },
      ],
    })
    expect(updateMutateAsync).not.toHaveBeenCalled()
  })

  it('sends a coverage only once it is ticked, with the amounts typed under it', async () => {
    const user = userEvent.setup()
    render(<PolicyForm mode="create" onClose={vi.fn()} onSuccess={vi.fn()} />)
    await fillPolicy(user)
    await addVehicle(user, RAM, 'Full Coverage', 0)

    // Unticked, a coverage shows no amounts at all: the checklist stays short.
    expect(screen.queryByLabelText('forms:insuranceCoverages.slots.premium')).not.toBeInTheDocument()

    await user.click(screen.getByLabelText('forms:insuranceCoverages.collision'))
    await user.type(screen.getByLabelText('forms:insurance.deductible', { selector: '#vehicle-0-coverage-collision-deductible' }), '500')
    await user.click(screen.getByRole('button', { name: 'common:create' }))

    await waitFor(() => expect(createMutateAsync).toHaveBeenCalledTimes(1))
    const { vehicles } = createMutateAsync.mock.calls[0][0]
    expect(vehicles[0].coverages).toEqual([
      {
        coverage_key: 'collision',
        limit_primary: null,
        limit_secondary: null,
        deductible: '500',
        premium: null,
      },
    ])
  })

  it('lets a bad amount be undone by unticking the coverage it was typed under', async () => {
    // Left behind, the hidden value keeps failing validation from a row that
    // is no longer on screen to show why the save does nothing.
    const user = userEvent.setup()
    render(<PolicyForm mode="create" onClose={vi.fn()} onSuccess={vi.fn()} />)
    await fillPolicy(user)
    await addVehicle(user, RAM, 'Full Coverage', 0)

    await user.click(screen.getByLabelText('forms:insuranceCoverages.collision'))
    await user.type(
      screen.getByLabelText('forms:insurance.deductible', {
        selector: '#vehicle-0-coverage-collision-deductible',
      }),
      '-1'
    )
    await user.click(screen.getByLabelText('forms:insuranceCoverages.collision'))
    await user.click(screen.getByRole('button', { name: 'common:create' }))

    await waitFor(() => expect(createMutateAsync).toHaveBeenCalledTimes(1))
    expect(createMutateAsync.mock.calls[0][0].vehicles[0].coverages).toEqual([])
  })

  it('sends a coverage carried with no amounts as a bare row', async () => {
    const user = userEvent.setup()
    render(<PolicyForm mode="create" onClose={vi.fn()} onSuccess={vi.fn()} />)
    await fillPolicy(user)
    await addVehicle(user, RAM, 'Full Coverage', 0)

    await user.click(screen.getByLabelText('forms:insuranceCoverages.roadsideAssistance'))
    await user.click(screen.getByRole('button', { name: 'common:create' }))

    await waitFor(() => expect(createMutateAsync).toHaveBeenCalledTimes(1))
    const { vehicles } = createMutateAsync.mock.calls[0][0]
    expect(vehicles[0].coverages).toEqual([
      {
        coverage_key: 'roadside_assistance',
        limit_primary: null,
        limit_secondary: null,
        deductible: null,
        premium: null,
      },
    ])
  })

  it("starts with the vehicle attached when opened from that vehicle's tab", () => {
    render(<PolicyForm mode="create" initialVin={MIRAGE} onClose={vi.fn()} onSuccess={vi.fn()} />)
    expect(screen.getByText('Mirage (2017 Mitsubishi Mirage)')).toBeInTheDocument()
    // Already attached, so it is no longer offered.
    const picker = screen.getByLabelText('insurance.addVehicle')
    expect(within(picker).queryByRole('option', { name: /Mirage/ })).not.toBeInTheDocument()
  })

  it('a suggested label is one tap, and is not offered twice', async () => {
    const user = userEvent.setup()
    render(<PolicyForm mode="create" onClose={vi.fn()} onSuccess={vi.fn()} />)
    await user.click(screen.getByRole('button', { name: 'forms:insuranceFieldLabels.agentPhone' }))

    expect(screen.getByDisplayValue('forms:insuranceFieldLabels.agentPhone')).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'forms:insuranceFieldLabels.agentPhone' })
    ).not.toBeInTheDocument()
  })

  it('"use this data" from a parsed document fills the policy AND attaches its matched vehicles', async () => {
    const user = userEvent.setup()
    cannedParse = {
      success: true,
      data: {
        provider: 'Progressive', policy_number: 'P-PDF', policy_type: 'Full Coverage',
        start_date: '2026-01-01', end_date: '2026-07-01', premium_amount: '600.00',
        premium_frequency: 'Semi-Annual', deductible: null,  notes: null,
      },
      vehicles: [
        { vin: RAM, matched: true, vehicle_name: 'Ram', premium_share: '320.00', deductible: '500.00', coverages: [{ coverage_key: 'collision', deductible: '500.00' }] },
        { vin: 'NOTINGARAGE000003', matched: false, vehicle_name: null, premium_share: '99.00', deductible: null, coverages: [] },
      ],
      confidence: {}, confidence_score: 90, parser_used: 'progressive', warnings: [],
    }
    render(<PolicyForm mode="create" onClose={vi.fn()} onSuccess={vi.fn()} />)
    await user.click(screen.getByRole('button', { name: 'insuranceForm.importFromPdf' }))
    await user.click(screen.getByRole('button', { name: 'fake-use-parse' }))
    await user.click(screen.getByRole('button', { name: 'common:create' }))

    await waitFor(() => expect(createMutateAsync).toHaveBeenCalledTimes(1))
    const payload = createMutateAsync.mock.calls[0][0]
    expect(payload.policy_number).toBe('P-PDF')
    expect(payload.vehicles).toEqual([
      { vin: RAM, policy_type: 'Full Coverage', premium_share: 320, deductible: 500, notes: null,
        coverages: [{ coverage_key: 'collision', limit_primary: null, limit_secondary: null, deductible: '500', premium: null }], fields: [] },
    ])
  })
})

describe('PolicyForm — allocation feedback', () => {
  it('shows the even split an empty share will resolve to, and warns when shares exceed the premium', async () => {
    const user = userEvent.setup()
    render(<PolicyForm mode="create" onClose={vi.fn()} onSuccess={vi.fn()} />)
    await fillPolicy(user, '600')
    await addVehicle(user, RAM, 'Full Coverage', 0)
    await addVehicle(user, MIRAGE, 'Liability', 1)

    // Nothing explicit: both vehicles take the even split.
    for (const input of screen.getAllByLabelText('insurance.vehicleShare')) {
      expect(input).toHaveAttribute('placeholder', 'insurance.evenSplit')
    }
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()

    await user.type(screen.getAllByLabelText('insurance.vehicleShare')[0], '700')
    expect(await screen.findByRole('alert')).toHaveTextContent('insurance.overAllocated')
  })

  it('warns when every share is fixed but they do not add up to the premium', async () => {
    const user = userEvent.setup()
    render(<PolicyForm mode="edit" policy={existing()} onClose={vi.fn()} onSuccess={vi.fn()} />)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument() // 400 + 200 = 600

    const premium = screen.getByLabelText('insurance.policyPremium')
    await user.clear(premium)
    await user.type(premium, '700')
    expect(await screen.findByRole('alert')).toHaveTextContent('insurance.underAllocated')
  })
})

describe('PolicyForm — edit and replace', () => {
  it('lets a named field be moved to where it belongs and saves that order', async () => {
    const user = userEvent.setup()
    const twoFields = existing({
      fields: [
        { label: 'Agent Phone', value: '555-0100' },
        { label: 'Claims Phone', value: '555-0199' },
      ],
    })
    render(<PolicyForm mode="edit" policy={twoFields} onClose={vi.fn()} onSuccess={vi.fn()} />)

    // The first field cannot go up and the last cannot go down: there is
    // nowhere for them to go, and a no-op button reads as a broken one.
    const up = screen.getAllByRole('button', { name: 'insurance.moveFieldUp' })
    expect(up[0]).toBeDisabled()
    await user.click(up[1])
    await user.click(screen.getByRole('button', { name: 'common:update' }))

    await waitFor(() => expect(updateMutateAsync).toHaveBeenCalledTimes(1))
    expect(updateMutateAsync.mock.calls[0][0].fields).toEqual([
      { label: 'Claims Phone', value: '555-0199' },
      { label: 'Agent Phone', value: '555-0100' },
    ])
  })


  it('edit sends the premium and the COMPLETE vehicle list together, keeping text it does not show', async () => {
    const user = userEvent.setup()
    render(<PolicyForm mode="edit" policy={existing()} onClose={vi.fn()} onSuccess={vi.fn()} />)
    await user.click(screen.getByRole('button', { name: 'common:update' }))

    await waitFor(() => expect(updateMutateAsync).toHaveBeenCalledTimes(1))
    const payload = updateMutateAsync.mock.calls[0][0]
    expect(payload.id).toBe(7)
    expect(payload.premium_amount).toBe(600)
    expect(payload.fields).toEqual([{ label: 'Agent Phone', value: '555-0100' }])
    expect(payload.vehicles).toEqual([
      {
        vin: RAM, policy_type: 'Full Coverage', premium_share: 400, deductible: 500,
        notes: null, effective_to: null,
        coverages: [
          {
            coverage_key: 'collision',
            limit_primary: null,
            limit_secondary: null,
            deductible: '500',
            premium: null,
          },
        ],
        fields: [{ label: 'Lienholder', value: 'Ally' }],
      },
      {
        vin: MIRAGE, policy_type: 'Liability', premium_share: 200, deductible: null,
        notes: null, effective_to: null, coverages: [], fields: [],
      },
    ])
  })

  it('never sends a vehicle list for a policy covering vehicles the user cannot see (it would remove them)', async () => {
    const user = userEvent.setup()
    render(
      <PolicyForm mode="edit" policy={existing({ other_vehicle_count: 1 })} onClose={vi.fn()} onSuccess={vi.fn()} />
    )
    expect(screen.getByText('insurance.vehiclesLocked')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'common:update' }))

    await waitFor(() => expect(updateMutateAsync).toHaveBeenCalledTimes(1))
    expect(updateMutateAsync.mock.calls[0][0]).not.toHaveProperty('vehicles')
  })

  it('switching insurers starts blank, carries the vehicles, and posts to replace', async () => {
    const user = userEvent.setup()
    render(<PolicyForm mode="replace" policy={existing()} onClose={vi.fn()} onSuccess={vi.fn()} />)
    expect(screen.getByLabelText('insurance.provider *')).toHaveValue('')
    // The new term starts where the old one ends.
    expect(screen.getByLabelText('common:startDate *')).toHaveValue('2026-07-01')

    await user.type(screen.getByLabelText('insurance.provider *'), 'GEICO')
    await user.type(screen.getByLabelText('insurance.policyNumber *'), 'G-7')
    await user.type(screen.getByLabelText('common:endDate *'), '2027-01-01')
    await user.type(screen.getByLabelText('insurance.endOldOn'), '2026-06-15')
    await user.click(screen.getByRole('button', { name: 'common:create' }))

    await waitFor(() => expect(replaceMutateAsync).toHaveBeenCalledTimes(1))
    expect(replaceMutateAsync).toHaveBeenCalledWith({
      id: 7,
      provider: 'GEICO',
      policy_number: 'G-7',
      // Follows "end the old policy on": a switch may not overlap the old term.
      start_date: '2026-06-15',
      end_date: '2027-01-01',
      premium_amount: null,
      premium_frequency: 'Semi-Annual',
      notes: null,
      // The vehicles go with their coverage TYPE prefilled and everything else
      // blank: a new insurer's deductibles and limits are not the old one's.
      vehicles: [
        { vin: RAM, policy_type: 'Full Coverage', premium_share: null, deductible: null, notes: null, coverages: [], fields: [] },
        { vin: MIRAGE, policy_type: 'Liability', premium_share: null, deductible: null, notes: null, coverages: [], fields: [] },
      ],
      end_old_on: '2026-06-15',
    })
    expect(createMutateAsync).not.toHaveBeenCalled()
  })
})

describe('PolicyForm — code-review regressions', () => {
  it('switching insurers on a policy with HIDDEN vehicles sends no vehicle list, so none is left behind (CF-R1-H1)', async () => {
    const user = userEvent.setup()
    render(
      <PolicyForm mode="replace" policy={existing({ other_vehicle_count: 1 })} onClose={vi.fn()} onSuccess={vi.fn()} />
    )
    expect(screen.getByText('insurance.vehiclesLocked')).toBeInTheDocument()
    await user.type(screen.getByLabelText('insurance.provider *'), 'GEICO')
    await user.type(screen.getByLabelText('insurance.policyNumber *'), 'G-7')
    await user.type(screen.getByLabelText('common:endDate *'), '2027-01-01')
    await user.click(screen.getByRole('button', { name: 'common:create' }))

    await waitFor(() => expect(replaceMutateAsync).toHaveBeenCalledTimes(1))
    const payload = replaceMutateAsync.mock.calls[0][0]
    expect(payload).not.toHaveProperty('vehicles')
    expect(payload).not.toHaveProperty('vins')
  })

  it('switching insurers with a vehicle the user can only READ carries everything over instead of failing (CF-R2-M1)', async () => {
    const user = userEvent.setup()
    const policy = existing()
    policy.vehicles![1] = { ...policy.vehicles![1], can_edit: false }
    render(<PolicyForm mode="replace" policy={policy} onClose={vi.fn()} onSuccess={vi.fn()} />)
    expect(screen.getByText('insurance.vehiclesLocked')).toBeInTheDocument()
    await user.type(screen.getByLabelText('insurance.provider *'), 'GEICO')
    await user.type(screen.getByLabelText('insurance.policyNumber *'), 'G-7')
    await user.type(screen.getByLabelText('common:endDate *'), '2027-01-01')
    await user.click(screen.getByRole('button', { name: 'common:create' }))

    await waitFor(() => expect(replaceMutateAsync).toHaveBeenCalledTimes(1))
    // Creating a link needs write access to the vehicle; carrying one does not.
    expect(replaceMutateAsync.mock.calls[0][0]).not.toHaveProperty('vehicles')
  })

  it('a mid-term switch starts the new policy the day the old one ends, and says where removed vehicles go (PR #177 review)', async () => {
    const user = userEvent.setup()
    render(<PolicyForm mode="replace" policy={existing()} onClose={vi.fn()} onSuccess={vi.fn()} />)
    expect(screen.queryByText('insurance.partialSwitch')).not.toBeInTheDocument()

    await user.type(screen.getByLabelText('insurance.endOldOn'), '2026-06-15')
    // The backend refuses a new policy that overlaps the old one.
    expect(screen.getByLabelText('common:startDate *')).toHaveValue('2026-06-15')

    await user.click(screen.getAllByRole('button', { name: 'insurance.removeVehicle' })[1])
    expect(screen.getByText('insurance.partialSwitch')).toBeInTheDocument()
  })

  it("switching insurers saves the NEW insurer's coverage edits instead of discarding them (CF-R1-H2)", async () => {
    const user = userEvent.setup()
    render(<PolicyForm mode="replace" policy={existing()} onClose={vi.fn()} onSuccess={vi.fn()} />)
    await user.type(screen.getByLabelText('insurance.provider *'), 'GEICO')
    await user.type(screen.getByLabelText('insurance.policyNumber *'), 'G-7')
    await user.type(screen.getByLabelText('common:endDate *'), '2027-01-01')
    await user.selectOptions(screen.getAllByLabelText('insurance.policyType *')[1], 'Full Coverage')
    await user.type(screen.getAllByLabelText('insurance.deductible')[0], '1000')
    await user.click(screen.getByRole('button', { name: 'common:create' }))

    await waitFor(() => expect(replaceMutateAsync).toHaveBeenCalledTimes(1))
    const { vehicles } = replaceMutateAsync.mock.calls[0][0]
    expect(vehicles[0]).toMatchObject({ vin: RAM, deductible: 1000 })
    expect(vehicles[1]).toMatchObject({ vin: MIRAGE, policy_type: 'Full Coverage' })
  })

  it('a premium change with the vehicle list locked says what happens to the shares (CF-R1-M2)', async () => {
    const user = userEvent.setup()
    render(
      <PolicyForm mode="edit" policy={existing({ other_vehicle_count: 1 })} onClose={vi.fn()} onSuccess={vi.fn()} />
    )
    const premium = screen.getByLabelText('insurance.policyPremium')
    await user.clear(premium)
    await user.type(premium, '700')
    await user.click(screen.getByRole('button', { name: 'common:update' }))

    await waitFor(() => expect(updateMutateAsync).toHaveBeenCalledTimes(1))
    const payload = updateMutateAsync.mock.calls[0][0]
    expect(payload.share_strategy).toBe('rescale')
    expect(payload).not.toHaveProperty('vehicles')
  })

  it('a vehicle the user can see but not write is shown read-only, with no remove control (CF-R1-M1)', () => {
    const policy = existing()
    policy.vehicles![1] = { ...policy.vehicles![1], can_edit: false }
    render(<PolicyForm mode="edit" policy={policy} onClose={vi.fn()} onSuccess={vi.fn()} />)

    expect(screen.getByText('insurance.vehicleReadOnly')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'insurance.removeVehicle' })).toHaveLength(1)
    expect(screen.getAllByLabelText('insurance.deductible')[0]).toBeEnabled()
    expect(screen.getAllByLabelText('insurance.deductible')[1]).toBeDisabled()
  })

  it('a parsed document fills in the vehicle whose tab opened the form instead of skipping it (CF-R1-M3)', async () => {
    const user = userEvent.setup()
    cannedParse = {
      success: true,
      data: {
        provider: 'Progressive', policy_number: 'P-PDF', policy_type: 'Liability',
        start_date: '2026-01-01', end_date: '2026-07-01', premium_amount: '280.00',
        premium_frequency: 'Semi-Annual', deductible: null,  notes: null,
      },
      vehicles: [{ vin: MIRAGE, matched: true, vehicle_name: 'Mirage', premium_share: '280.00', deductible: '250.00', coverages: [] }],
      confidence: {}, confidence_score: 90, parser_used: 'progressive', warnings: [],
    }
    render(<PolicyForm mode="create" initialVin={MIRAGE} onClose={vi.fn()} onSuccess={vi.fn()} />)
    await user.click(screen.getByRole('button', { name: 'insuranceForm.importFromPdf' }))
    await user.click(screen.getByRole('button', { name: 'fake-use-parse' }))
    await user.click(screen.getByRole('button', { name: 'common:create' }))

    await waitFor(() => expect(createMutateAsync).toHaveBeenCalledTimes(1))
    expect(createMutateAsync.mock.calls[0][0].vehicles).toEqual([
      { vin: MIRAGE, policy_type: 'Liability', premium_share: 280, deductible: 250, notes: null, coverages: [], fields: [] },
    ])
  })

  it('an incomplete named field says why Save did nothing (CF-R1-M4)', async () => {
    const user = userEvent.setup()
    render(<PolicyForm mode="create" onClose={vi.fn()} onSuccess={vi.fn()} />)
    await fillPolicy(user)
    await user.click(screen.getByRole('button', { name: 'forms:insuranceFieldLabels.agentPhone' }))
    // A label with no value.
    await user.click(screen.getByRole('button', { name: 'common:create' }))

    expect(await screen.findByText('insurance.fieldIncomplete')).toBeInTheDocument()
    expect(createMutateAsync).not.toHaveBeenCalled()
  })

  it('the split placeholder rounds DOWN like the backend and says "about" when cents are left over (CF-R1-F1)', async () => {
    const user = userEvent.setup()
    render(<PolicyForm mode="create" onClose={vi.fn()} onSuccess={vi.fn()} />)
    await fillPolicy(user, '100')
    await addVehicle(user, RAM, 'Full Coverage', 0)
    await addVehicle(user, MIRAGE, 'Liability', 1)
    // 100 / 2 is exact.
    expect(screen.getAllByLabelText('insurance.vehicleShare')[0]).toHaveAttribute('placeholder', 'insurance.evenSplit')

    const premium = screen.getByLabelText('insurance.policyPremium')
    await user.clear(premium)
    await user.type(premium, '100.01')
    await waitFor(() =>
      expect(screen.getAllByLabelText('insurance.vehicleShare')[0]).toHaveAttribute('placeholder', 'insurance.evenSplitAbout')
    )
  })
})

describe('PolicyForm: a rejected submit (G1b-69)', () => {
  const premiumRejected = {
    isAxiosError: true,
    message: 'Request failed with status code 422',
    response: {
      status: 422,
      data: { detail: [{ type: 'decimal_parsing', loc: ['body', 'premium_amount'], msg: 'Input should be a valid decimal' }] },
    },
  }

  it('toasts on a non-422 failure instead of staying silent', async () => {
    createMutateAsync.mockRejectedValueOnce(new Error('Network Error'))
    const user = userEvent.setup()
    render(<PolicyForm mode="create" onClose={vi.fn()} onSuccess={vi.fn()} />)
    await fillPolicy(user)
    await addVehicle(user, RAM, 'Full Coverage', 0)
    await user.click(screen.getByRole('button', { name: 'common:create' }))

    await waitFor(() => expect(toast.error).toHaveBeenCalledTimes(1))
    expect(toast.error).toHaveBeenCalledWith('Failed to insurance.saveAction. Network Error')
    expect(document.getElementById('premium_amount-error')).toBeNull()
  })

  it('shows a bad premium under its own field and does not toast', async () => {
    createMutateAsync.mockRejectedValueOnce(premiumRejected)
    const user = userEvent.setup()
    render(<PolicyForm mode="create" onClose={vi.fn()} onSuccess={vi.fn()} />)
    await fillPolicy(user)
    await addVehicle(user, RAM, 'Full Coverage', 0)
    await user.click(screen.getByRole('button', { name: 'common:create' }))

    await waitFor(() => expect(document.getElementById('premium_amount-error')).not.toBeNull())
    expect(document.getElementById('premium_amount-error')).toHaveTextContent('Input should be a valid decimal')
    expect(toast.error).not.toHaveBeenCalled()
  })

  it('saves a comma-decimal premium as a number', async () => {
    const user = userEvent.setup()
    render(<PolicyForm mode="create" onClose={vi.fn()} onSuccess={vi.fn()} />)
    await fillPolicy(user, '1234,50')
    await addVehicle(user, RAM, 'Full Coverage', 0)
    await user.click(screen.getByRole('button', { name: 'common:create' }))

    await waitFor(() => expect(createMutateAsync).toHaveBeenCalledTimes(1))
    expect(createMutateAsync.mock.calls[0][0]).toMatchObject({ premium_amount: 1234.5 })
  })
})
