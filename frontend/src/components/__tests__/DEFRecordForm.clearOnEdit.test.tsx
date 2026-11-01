import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, waitFor } from '@testing-library/react'
import { render } from '../../__tests__/test-utils'

// Clearing a field on edit has to reach the API as null. The update route
// skips keys that aren't sent (exclude_unset), so an undefined here kept the
// old value no matter what the form showed. Create is unchanged.

const createMock = vi.fn().mockResolvedValue({})
const updateMock = vi.fn().mockResolvedValue({})

vi.mock('../../hooks/queries/useDEFRecords', () => ({
  useCreateDEFRecord: () => ({ mutateAsync: createMock }),
  useUpdateDEFRecord: () => ({ mutateAsync: updateMock }),
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

import DEFRecordForm from '../DEFRecordForm'

const VIN = 'TEST12345678901234'
const defForm = () => document.getElementById('def-record-form') as HTMLFormElement
const field = (id: string) => document.getElementById(id) as HTMLInputElement
const CLEARABLE = ['odometer_km', 'liters', 'price_per_unit', 'cost', 'fill_level', 'source', 'brand', 'notes']

const RECORD = {
  id: 5, vin: VIN, date: '2026-02-10', odometer_km: 55000, liters: 5.5, price_per_unit: 1.1,
  cost: 6.05, fill_level: 0.5, source: 'Dealer', brand: 'BlueDEF', notes: 'old',
} as never

beforeEach(() => vi.clearAllMocks())

describe('DEFRecordForm: clearing a field on edit', () => {
  it('sends null for every optional field the user cleared', async () => {
    render(<DEFRecordForm vin={VIN} record={RECORD} onClose={vi.fn()} onSuccess={vi.fn()} />)
    for (const id of CLEARABLE) fireEvent.change(field(id), { target: { value: '' } })
    fireEvent.submit(defForm())
    await waitFor(() => expect(updateMock).toHaveBeenCalled())

    const payload = updateMock.mock.calls[0][0] as Record<string, unknown>
    for (const key of CLEARABLE) expect(payload[key], key).toBeNull()
  })

  it('create still leaves an empty field out', async () => {
    render(<DEFRecordForm vin={VIN} onClose={vi.fn()} onSuccess={vi.fn()} />)
    fireEvent.submit(defForm())
    await waitFor(() => expect(createMock).toHaveBeenCalled())

    const payload = createMock.mock.calls[0][0] as Record<string, unknown>
    for (const key of CLEARABLE) expect(payload[key], key).toBeUndefined()
  })
})
