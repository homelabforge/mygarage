/**
 * Editing a fill-up in a comma-decimal language and tabbing through the price
 * must save the price it opened with. RHF writes a seeded 1.799 into the box as
 * "1.799", and a blur used to re-read that in German as 1799.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { screen, waitFor, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { render } from '../../__tests__/test-utils'
import { setActiveLocale } from '@/constants/i18n'
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

const price = () => document.getElementById('price_per_unit') as HTMLInputElement

/** Open the fill-up, tab through the price without typing, save, and hand back the PUT body. */
async function tabThroughPriceAndSave(): Promise<Record<string, unknown>> {
  render(<FuelRecordForm vin={VIN} record={fillUp} onClose={vi.fn()} onSuccess={vi.fn()} />)
  await waitFor(() => expect(price()).toHaveValue('1.799'))
  const user = userEvent.setup()
  await user.click(price())
  await user.tab()
  fireEvent.submit(drawerForm())
  await waitFor(() => expect(mockedApiPut).toHaveBeenCalled())
  return mockedApiPut.mock.calls.at(-1)?.[1] as Record<string, unknown>
}

beforeEach(() => {
  vi.clearAllMocks()
  mockedApiPut.mockResolvedValue({ data: {} })
  mockedApiGet.mockImplementation((url: string) =>
    Promise.resolve({ data: String(url).includes('/fuel') ? { records: [] } : vehicle })
  )
  localStorage.clear()
})
afterEach(() => setActiveLocale('en'))

describe('FuelRecordForm: the seeded price survives a pass through the field', () => {
  it('de: a 1.799 EUR/L fill-up still saves 1.799, not 1799', async () => {
    setActiveLocale('de')
    const body = await tabThroughPriceAndSave()
    expect(body.price_per_unit).toBe(1.799)
  })

  it('en: the same fill-up saves 1.799 (guard)', async () => {
    // Guard: passes on main, where en reads the dot as a decimal anyway.
    const body = await tabThroughPriceAndSave()
    expect(body.price_per_unit).toBe(1.799)
  })
})
