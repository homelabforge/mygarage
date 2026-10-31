import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, waitFor } from '@testing-library/react'
import { render } from '../../__tests__/test-utils'

// Clearing a field on edit has to reach the API as null. The update route
// skips keys that aren't sent (exclude_unset), so an undefined here kept the
// old value no matter what the form showed. Create is unchanged.

const createMock = vi.fn().mockResolvedValue({})
const updateMock = vi.fn().mockResolvedValue({})

vi.mock('../../hooks/queries/usePropaneRecords', () => ({
  useCreatePropaneRecord: () => ({ mutateAsync: createMock }),
  useUpdatePropaneRecord: () => ({ mutateAsync: updateMock }),
}))
vi.mock('../../hooks/useUnitPreference', async () => {
  const { METRIC_UNITS } = await import('@/__tests__/factories')
  // UnitSession reads the account half too; same answer, nothing to pin here.
  const unitPreference = () => ({ system: 'metric', showBoth: false, units: METRIC_UNITS })
  return {
    useUnitPreference: unitPreference,
    useAccountUnitPreference: unitPreference,
  }
})
vi.mock('../../hooks/useCurrencySymbol', () => ({ useCurrencySymbol: () => '$' }))

import PropaneRecordForm from '../PropaneRecordForm'

const VIN = 'TEST12345678901234'
const propaneForm = () => document.getElementById('propane-record-form') as HTMLFormElement
const field = (id: string) => document.getElementById(id) as HTMLInputElement
// The tank pair first: editing either one recalculates the volume.
const INPUTS = ['tank_size_kg', 'tank_quantity', 'propane_liters', 'price_per_unit', 'cost', 'vendor', 'notes']
const CLEARABLE = ['tank_size_kg', 'tank_quantity', 'propane_liters', 'price_per_unit', 'cost', 'notes']

const RECORD = {
  id: 6, vin: VIN, date: '2026-02-10', propane_liters: 34, tank_size_kg: 9.07, tank_quantity: 2,
  price_per_unit: 0.9, price_basis: 'per_volume', cost: 30.6, notes: 'Vendor: Ferrell\nold',
} as never

beforeEach(() => vi.clearAllMocks())

describe('PropaneRecordForm: clearing a field on edit', () => {
  it('sends null for every optional field the user cleared, the tank pair together', async () => {
    render(<PropaneRecordForm vin={VIN} record={RECORD} onClose={vi.fn()} onSuccess={vi.fn()} />)
    for (const id of INPUTS) fireEvent.change(field(id), { target: { value: '' } })
    fireEvent.submit(propaneForm())
    await waitFor(() => expect(updateMock).toHaveBeenCalled())

    const payload = updateMock.mock.calls[0][0] as Record<string, unknown>
    for (const key of CLEARABLE) expect(payload[key], key).toBeNull()
  })

  it('create still leaves an empty field out', async () => {
    render(<PropaneRecordForm vin={VIN} onClose={vi.fn()} onSuccess={vi.fn()} />)
    fireEvent.change(field('propane_liters'), { target: { value: '20' } })
    fireEvent.submit(propaneForm())
    await waitFor(() => expect(createMock).toHaveBeenCalled())

    const payload = createMock.mock.calls[0][0] as Record<string, unknown>
    for (const key of ['tank_size_kg', 'tank_quantity', 'price_per_unit', 'cost', 'notes']) {
      expect(payload[key], key).toBeUndefined()
    }
  })
})
