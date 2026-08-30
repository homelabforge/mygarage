import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { render } from '../../__tests__/test-utils'
import type { WarrantyRecord } from '../../types/warranty'

const createMutateAsync = vi.fn().mockResolvedValue({})
const updateMutateAsync = vi.fn().mockResolvedValue({})
vi.mock('../../hooks/queries/useWarrantyRecords', () => ({
  useCreateWarrantyRecord: () => ({ mutateAsync: createMutateAsync }),
  useUpdateWarrantyRecord: () => ({ mutateAsync: updateMutateAsync }),
}))
// The imperial PRESET, resolved set included: `useUnitFormat` reads `units`,
// and a mock that supplied only the collapsed `system` would hand the form an
// undefined set. Mixed sets, where `system` and `units.distance` disagree, are
// exercised in WarrantyForm.mixedUnits.test.tsx.
vi.mock('../../hooks/useUnitPreference', async () => {
  const { IMPERIAL_UNITS } = await import('@/__tests__/factories')
  return {
    useUnitPreference: () => ({
      system: 'imperial',
      showBoth: false,
      units: IMPERIAL_UNITS,
      gallonStandard: 'us',
    }),
  }
})

import WarrantyForm from '../WarrantyForm'

beforeEach(() => vi.clearAllMocks())

// M1: fill via the LABEL→control association (getByLabelText) with async userEvent — realistic
// typing/selection/disabled behaviour, never fireEvent.change and never document.getElementById,
// so a dropped Field htmlFor/id link fails the test instead of being bypassed. The i18n mock
// echoes keys and imperial is mocked, so Field renders these exact accessible names (label +
// ' *' for required + ' (mi)' for the unit) — identical pre- and post-restyle (verified).
const fillCreate = async (user: ReturnType<typeof userEvent.setup>) => {
  await user.selectOptions(screen.getByLabelText('warranty.warrantyType *'), 'Manufacturer')
  await user.clear(screen.getByLabelText('insurance.provider'))
  await user.type(screen.getByLabelText('insurance.provider'), 'Toyota')
  await user.clear(screen.getByLabelText('common:startDate *'))
  await user.type(screen.getByLabelText('common:startDate *'), '2026-01-01')
  await user.clear(screen.getByLabelText('common:endDate'))
  await user.type(screen.getByLabelText('common:endDate'), '2030-01-01')
  await user.clear(screen.getByLabelText('warranty.mileageLimit (mi)'))
  await user.type(screen.getByLabelText('warranty.mileageLimit (mi)'), '60000')
  await user.clear(screen.getByLabelText('warranty.coverageDetails'))
  await user.type(screen.getByLabelText('warranty.coverageDetails'), 'Full coverage')
  await user.clear(screen.getByLabelText('insurance.policyNumber'))
  await user.type(screen.getByLabelText('insurance.policyNumber'), 'W-1')
  await user.clear(screen.getByLabelText('common:notes'))
  await user.type(screen.getByLabelText('common:notes'), 'note')
}

describe('WarrantyForm — routing + canonical mileage + exact payload', () => {
  it('create submits the COMPLETE payload converting the mileage limit miles→km, and NEVER calls update (fails if a field is dropped, the raw display mileage is stored, or it misroutes)', async () => {
    const user = userEvent.setup()
    render(<WarrantyForm vin="V1" onClose={vi.fn()} onSuccess={vi.fn()} />)
    await fillCreate(user)
    await user.click(screen.getByRole('button', { name: 'common:create' }))
    await waitFor(() => expect(createMutateAsync).toHaveBeenCalledTimes(1))
    // 60000 mi x 1.60934 = 96560.4 km, NOT the raw 60000.
    expect(createMutateAsync).toHaveBeenCalledWith({
      warranty_type: 'Manufacturer',
      provider: 'Toyota',
      start_date: '2026-01-01',
      end_date: '2030-01-01',
      mileage_limit_km: 96560.4,
      coverage_details: 'Full coverage',
      policy_number: 'W-1',
      notes: 'note',
    })
    expect(updateMutateAsync).not.toHaveBeenCalled()
  })

  it('edit submits the UPDATE payload — routing id + edited field + round-tripped canonical km — and NEVER calls create (fails if it misroutes or drops the id)', async () => {
    const record = {
      id: 7, warranty_type: 'Powertrain', provider: 'Honda',
      start_date: '2025-01-01', end_date: '2029-01-01',
      mileage_limit_km: '96561', coverage_details: 'x', policy_number: 'P-9', notes: '',
    } as unknown as WarrantyRecord
    const user = userEvent.setup()
    render(<WarrantyForm vin="V1" record={record} onClose={vi.fn()} onSuccess={vi.fn()} />)
    await user.clear(screen.getByLabelText('insurance.provider'))
    await user.type(screen.getByLabelText('insurance.provider'), 'Honda Ltd')
    await user.click(screen.getByRole('button', { name: 'common:update' }))
    await waitFor(() => expect(updateMutateAsync).toHaveBeenCalledTimes(1))
    // The edit seeds the mileage from 96561 km, shown as 60000 mi
    // (96561 / 1.60934 = 60000.3728..., at the mi adapter's zero decimals).
    // The field was never touched, so the ORIGIN is posted back: 96561, not
    // the 96560.4 that re-converting 60000 mi would produce.
    // B1/LD4: assert the COMPLETE 9-property update object (id + all 8 body fields), not a
    // partial objectContaining — dropping a date/coverage/policy#/notes must FAIL the test.
    expect(updateMutateAsync).toHaveBeenCalledWith({
      id: 7,
      warranty_type: 'Powertrain',
      provider: 'Honda Ltd',
      start_date: '2025-01-01',
      end_date: '2029-01-01',
      mileage_limit_km: 96561,
      coverage_details: 'x',
      policy_number: 'P-9',
      notes: '',
    })
    expect(createMutateAsync).not.toHaveBeenCalled()
  })

  it('the Field labels resolve to the controls carrying the expected ids (fails if a Field htmlFor/id association is dropped)', () => {
    render(<WarrantyForm vin="V1" onClose={vi.fn()} onSuccess={vi.fn()} />)
    // M1: resolve THROUGH the label, then assert the control's id — exercising the
    // label→control link rather than reaching the control by id directly.
    expect(screen.getByLabelText('warranty.warrantyType *')).toHaveAttribute('id', 'warranty_type')
    expect(screen.getByLabelText('warranty.mileageLimit (mi)')).toHaveAttribute('id', 'mileage_limit_km')
  })
})
