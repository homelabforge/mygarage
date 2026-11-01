/**
 * Unreadable text in a More details field survives the section closing and
 * opening again. RHF writes the held value back into the new box, and for
 * unreadable text that value is the INVALID_NUMBER symbol, which used to throw.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, waitFor, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { render } from '../../__tests__/test-utils'
import FuelRecordForm from '../FuelRecordForm'
import type { FuelRecord } from '../../types/fuel'

const drawerForm = (): HTMLFormElement =>
  screen.getByRole('dialog').querySelector('form') as HTMLFormElement

const mockedApiGet = vi.fn()
const mockedApiPut = vi.fn().mockResolvedValue({ data: {} })

vi.mock('../../services/api', () => ({
  default: {
    get: (...args: unknown[]) => mockedApiGet(...args),
    post: vi.fn().mockResolvedValue({ data: {} }),
    put: (...args: unknown[]) => mockedApiPut(...args),
  },
}))
vi.mock('../../hooks/useUnitPreference', async () => {
  const { METRIC_UNITS } = await import('@/__tests__/factories')
  const unitPreference = () => ({ system: 'metric', showBoth: false, units: METRIC_UNITS })
  return {
    useUnitPreference: unitPreference,
    useAccountUnitPreference: unitPreference,
  }
})
vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({ user: null }),
}))
vi.mock('../../hooks/useTimeFormat', () => ({
  useTimeFormat: () => ({ timeFormat: '24h' }),
}))

const VIN = 'TEST12345678901234'
const vehicle = {
  vin: VIN, nickname: 'Test', vehicle_type: 'Car', year: 2024, make: 'Toyota', model: 'Camry',
  fuel_type: 'gasoline', created_at: '2024-01-15T00:00:00Z', archived_visible: true,
}

const fillUp = {
  id: 42, vin: VIN, date: '2026-03-01', is_full_tank: true, missed_fillup: false, is_hauling: false,
  odometer_km: 50000, liters: 40, price_per_unit: 1.799, price_basis: 'per_volume', cost: 71.96,
} as unknown as FuelRecord

const obc = () => document.getElementById('obc_l_per_100km') as HTMLInputElement
const moreDetails = () => screen.getByRole('button', { name: /fuel\.moreDetails/ })

beforeEach(() => {
  vi.clearAllMocks()
  mockedApiPut.mockResolvedValue({ data: {} })
  mockedApiGet.mockImplementation((url: string) =>
    Promise.resolve({ data: String(url).includes('/fuel') ? { records: [] } : vehicle })
  )
  localStorage.clear()
  localStorage.setItem('fuel_form:more_details_expanded', '1')
})

describe('FuelRecordForm: unreadable text in a section that closes and opens', () => {
  it('comes back as typed, and the save is still refused', async () => {
    render(<FuelRecordForm vin={VIN} record={fillUp} onClose={vi.fn()} onSuccess={vi.fn()} />)
    await waitFor(() => expect(obc()).toBeInTheDocument())
    const user = userEvent.setup()
    await user.type(obc(), 'abc')
    await user.click(moreDetails())
    expect(obc()).toBeNull()
    await user.click(moreDetails())
    expect(obc()).toHaveValue('abc')
    fireEvent.submit(drawerForm())
    await waitFor(() => expect(obc()).toHaveAttribute('aria-invalid', 'true'))
    expect(mockedApiPut).not.toHaveBeenCalled()
  })
})
