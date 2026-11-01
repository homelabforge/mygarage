/**
 * The outside temperature is typed text like every other number on the form
 * (G1b-21). It used to be a native number box with a step, so a comma decimal
 * read as blank and dropped the reading, 21.25 tripped the browser's step
 * check, and a bad entry vanished instead of saying so.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import type { ReactNode } from 'react'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { render } from '../../__tests__/test-utils'
import { IMPERIAL_UNITS, METRIC_UNITS } from '../../__tests__/factories'
import { setActiveLocale } from '@/constants/i18n'
import type { UnitSet } from '../../types/units'
import FuelRecordForm from '../FuelRecordForm'
import type { FuelRecord } from '../../types/fuel'

const mockedApiGet = vi.fn()
const mockedApiPut = vi.fn().mockResolvedValue({ data: {} })

vi.mock('../../services/api', () => ({
  default: {
    get: (...args: unknown[]) => mockedApiGet(...args),
    post: vi.fn().mockResolvedValue({ data: {} }),
    put: (...args: unknown[]) => mockedApiPut(...args),
  },
}))

let units: UnitSet = METRIC_UNITS
vi.mock('../../hooks/useUnitPreference', () => {
  const unitPreference = () => ({ system: 'metric', showBoth: false, units })
  return { useUnitPreference: unitPreference, useAccountUnitPreference: unitPreference }
})
vi.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({ user: null }) }))
vi.mock('../../hooks/useTimeFormat', () => ({ useTimeFormat: () => ({ timeFormat: '24h' }) }))

// Keeps interpolated values, so a message can be checked for the bounds it names.
vi.mock('react-i18next', () => {
  const t = (key: string, options?: Record<string, unknown>): string => {
    const values = Object.entries(options ?? {})
      .filter(([name]) => name !== 'defaultValue')
      .map(([name, value]) => `${name}=${String(value)}`)
    return values.length > 0 ? `${key}(${values.join(', ')})` : key
  }
  const i18n = { language: 'en', changeLanguage: () => Promise.resolve() }
  return {
    useTranslation: () => ({ t, i18n }),
    Trans: ({ children }: { children: ReactNode }) => children,
    initReactI18next: { type: '3rdParty', init: () => {} },
  }
})

const VIN = 'TEST12345678901234'
const vehicle = {
  vin: VIN, nickname: 'Test', vehicle_type: 'Car', year: 2024, make: 'Toyota', model: 'Camry',
  fuel_type: 'gasoline', created_at: '2024-01-15T00:00:00Z', archived_visible: true,
}

const fillUp = {
  id: 42, vin: VIN, date: '2026-03-01', is_full_tank: true, missed_fillup: false, is_hauling: false,
  odometer_km: 50000, liters: 40, price_per_unit: 1.799, price_basis: 'per_volume', cost: 71.96,
} as unknown as FuelRecord

const temperature = () => screen.getByLabelText(/fuel\.outsideTemp/) as HTMLInputElement
const save = () => screen.getByRole('button', { name: 'common:update' })

async function openForm() {
  render(<FuelRecordForm vin={VIN} record={fillUp} onClose={vi.fn()} onSuccess={vi.fn()} />)
  await waitFor(() => expect(temperature()).toBeInTheDocument())
  return userEvent.setup()
}

function putBody(): Record<string, unknown> {
  const call = mockedApiPut.mock.calls[0]
  expect(call, 'no update PUT was made').toBeDefined()
  return call[1] as Record<string, unknown>
}

beforeEach(() => {
  vi.clearAllMocks()
  units = METRIC_UNITS
  mockedApiPut.mockResolvedValue({ data: {} })
  mockedApiGet.mockImplementation((url: string) =>
    Promise.resolve({ data: String(url).includes('/fuel') ? { records: [] } : vehicle })
  )
  localStorage.clear()
  localStorage.setItem('fuel_form:more_details_expanded', '1')
})

afterEach(() => setActiveLocale('en'))

describe('FuelRecordForm: outside temperature is typed text', () => {
  it('de: 21,5 degrees saves 21.5', async () => {
    setActiveLocale('de')
    const user = await openForm()
    await user.type(temperature(), '21,5')
    await user.click(save())
    await waitFor(() => expect(mockedApiPut).toHaveBeenCalled())
    expect(putBody().outside_temp_c).toBe(21.5)
  })

  it('21.25 saves through the Save button, nothing native blocks it', async () => {
    const user = await openForm()
    // jsdom never runs the step check, so ask the two things a browser would:
    // is there a step to miss, and does the form let the browser check at all.
    expect(temperature()).not.toHaveAttribute('step')
    expect(temperature()).toHaveAttribute('type', 'text')
    expect((screen.getByRole('dialog').querySelector('form') as HTMLFormElement).noValidate).toBe(true)
    await user.type(temperature(), '21.25')
    await user.click(save())
    await waitFor(() => expect(mockedApiPut).toHaveBeenCalled())
    expect(putBody().outside_temp_c).toBe(21.25)
  })

  it('text that is not a number says so and is not saved', async () => {
    const user = await openForm()
    await user.type(temperature(), 'abc')
    await user.click(save())
    expect(await screen.findByText(/^common:validation\.fuel\.outsideTempInvalid\b/)).toBeInTheDocument()
    expect(temperature()).toHaveAttribute('aria-invalid', 'true')
    expect(mockedApiPut).not.toHaveBeenCalled()
  })

  it('a lone minus sign, the first key of a negative, is not an error yet', async () => {
    // It read as text that isn't a number, so the error and aria-invalid flashed on the first keystroke.
    const user = await openForm()
    await user.type(temperature(), '-')
    expect(temperature()).not.toHaveAttribute('aria-invalid', 'true')
    expect(screen.queryByText(/^common:validation\.fuel\.outsideTempInvalid\b/)).toBeNull()
    await user.type(temperature(), '5')
    await user.click(save())
    await waitFor(() => expect(mockedApiPut).toHaveBeenCalled())
    expect(putBody().outside_temp_c).toBe(-5)
  })

  it('a lone minus sign left in the box is refused at save, not saved as blank', async () => {
    // Guard: passes on main too. Map the sign-only text to undefined and the save goes through blank.
    const user = await openForm()
    await user.type(temperature(), '-')
    await user.click(save())
    expect(await screen.findByText(/^common:validation\.fuel\.outsideTempInvalid\b/)).toBeInTheDocument()
    expect(mockedApiPut).not.toHaveBeenCalled()
  })

  it('a Fahrenheit user is told the bounds in Fahrenheit', async () => {
    // The API takes -60..70 C, which is -76..158 F.
    units = { ...IMPERIAL_UNITS, temperature: 'f' }
    const user = await openForm()
    await user.type(temperature(), '200')
    await user.click(save())
    // The mock prints every value the message was handed, so pick out the one it names.
    expect(
      await screen.findByText(/^common:validation\.fuel\.outsideTempTooHigh\(.*max=158\.0 °F/)
    ).toBeInTheDocument()
    expect(mockedApiPut).not.toHaveBeenCalled()

    await user.clear(temperature())
    await user.type(temperature(), '-100')
    expect(
      await screen.findByText(/^common:validation\.fuel\.outsideTempTooLow\(min=-76\.0 °F/)
    ).toBeInTheDocument()
  })
})
