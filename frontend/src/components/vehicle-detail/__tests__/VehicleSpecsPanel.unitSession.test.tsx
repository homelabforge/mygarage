/**
 * The specs editor keeps the units, and the draft, it opened with (R4).
 *
 * The REAL `useUnitPreference` runs on an anonymous client. On main the
 * editor reseeds on any units change and on any new vehicle object, so a flip
 * or a refetch mid-edit throws away what was typed.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { useState, type ReactElement, type ReactNode } from 'react'
import { act, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { render } from '../../../__tests__/test-utils'
import { IMPERIAL_UNITS, METRIC_UNITS } from '../../../__tests__/factories'
import { setUnitPrefs } from '../../../utils/unitPrefsStore'
import type { Vehicle } from '../../../types/vehicle'
import vehicleService from '../../../services/vehicleService'

vi.mock('../../../services/vehicleService', () => ({ default: { update: vi.fn() } }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('../../../contexts/AuthContext', () => ({
  useAuth: () => ({ user: null, isAuthenticated: false, defaultUnitPrefs: METRIC_UNITS }),
}))
// Keeps the interpolated unit, which the global `t: (key) => key` drops.
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: { unit?: string }) =>
      options?.unit ? `${key} (${options.unit})` : key,
    i18n: { language: 'en', changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children: ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: () => {} },
}))

import VehicleSpecsPanel from '../VehicleSpecsPanel'

const mockedUpdate = vi.mocked(vehicleService).update

const vehicle = {
  vin: 'TEST0000000000001',
  nickname: 'Test',
  vehicle_type: 'Car',
  usage_unit: 'distance',
  secondary_usage_enabled: false,
  oil_viscosity: '5W-30',
  oil_capacity_liters: '4.7',
  lug_nut_torque_nm: '135.0',
} as unknown as Vehicle

const panel = (v: Vehicle = vehicle): ReactElement => (
  <VehicleSpecsPanel vin="TEST0000000000001" vehicle={v} onUpdated={vi.fn()} />
)
/** The page's side of the loop: a save hands the server's row back as the vehicle. */
function Host(): ReactElement {
  const [current, setCurrent] = useState<Vehicle>(vehicle)
  return <VehicleSpecsPanel vin={current.vin} vehicle={current} onUpdated={setCurrent} />
}
const flipToImperial = (): void =>
  act(() => setUnitPrefs({ units: IMPERIAL_UNITS, unit_preference: null, show_both_units: false }))
const flipToMetric = (): void =>
  act(() => setUnitPrefs({ units: METRIC_UNITS, unit_preference: null, show_both_units: false }))

/** Open the editor and hand back its oil field. */
async function openOil(): Promise<{ drawer: HTMLElement; oil: HTMLInputElement }> {
  fireEvent.click(screen.getByRole('button', { name: 'detail.specs.editAria' }))
  const drawer = await screen.findByRole('dialog')
  const oil = within(drawer).getByLabelText(/detail\.specs\.oilCapacityWithUnit/) as HTMLInputElement
  return { drawer, oil }
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  // Bare event: the store re-reads everything, so it drops the last test's set.
  window.dispatchEvent(new Event('storage'))
  setUnitPrefs({ units: IMPERIAL_UNITS, unit_preference: null, show_both_units: false })
  mockedUpdate.mockResolvedValue(vehicle)
})

describe('VehicleSpecsPanel editor holds its units while open', () => {
  it('a flip to metric mid-edit keeps the typed quarts and stores them as quarts', async () => {
    render(panel())
    const { drawer, oil } = await openOil()
    fireEvent.change(oil, { target: { value: '12' } })

    flipToMetric()

    expect(oil.value).toBe('12')
    fireEvent.click(within(drawer).getByRole('button', { name: 'common:save' }))
    await waitFor(() => expect(mockedUpdate).toHaveBeenCalledTimes(1))
    // 12 US qt x 0.946352946 = 11.356 L, not 12 L.
    expect(mockedUpdate.mock.calls[0][1].oil_capacity_liters).toBeCloseTo(11.356, 3)
  })

  it('a flip while closed reaches the next open: label, seed and save are all litres', async () => {
    render(panel())
    flipToMetric()

    const { drawer, oil } = await openOil()

    expect(within(drawer).getByText('detail.specs.oilCapacityWithUnit (L)')).toBeInTheDocument()
    expect(oil.value).toBe('4.7')
    fireEvent.change(oil, { target: { value: '5' } })
    fireEvent.click(within(drawer).getByRole('button', { name: 'common:save' }))
    await waitFor(() => expect(mockedUpdate).toHaveBeenCalledTimes(1))
    expect(mockedUpdate.mock.calls[0][1].oil_capacity_liters).toBe(5)
  })

  it('a refetch handing in a new vehicle object mid-edit keeps the draft', async () => {
    const { rerender } = render(panel())
    const { oil } = await openOil()
    fireEvent.change(oil, { target: { value: '12' } })

    // Same vehicle, fresh object, as a sidecar save or a refetch delivers it.
    rerender(panel({ ...vehicle, nickname: 'Renamed' } as Vehicle))

    expect(oil.value).toBe('12')
  })

  it('guard: an open editor that lands on another vehicle reseeds from it', async () => {
    flipToMetric()
    const { rerender } = render(panel())
    const { oil } = await openOil()
    expect(oil.value).toBe('4.7')
    fireEvent.change(oil, { target: { value: '12' } })

    const other = { ...vehicle, vin: 'TEST0000000000002', oil_capacity_liters: '3.2' } as unknown as Vehicle
    rerender(<VehicleSpecsPanel vin={other.vin} vehicle={other} onUpdated={vi.fn()} />)

    await waitFor(() => expect(oil.value).toBe('3.2'))
  })
})

describe('VehicleSpecsPanel editor after a save', () => {
  it('guard: reopening shows what the server stored, not what was typed', async () => {
    flipToMetric()
    mockedUpdate.mockResolvedValue({ ...vehicle, oil_capacity_liters: '6.5', oil_viscosity: '0W-20' } as Vehicle)
    render(<Host />)
    const first = await openOil()
    fireEvent.change(first.oil, { target: { value: '6.2' } })
    fireEvent.click(within(first.drawer).getByRole('button', { name: 'common:save' }))
    await waitFor(() => expect(mockedUpdate).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())

    const again = await openOil()

    await waitFor(() => expect(again.oil.value).toBe('6.5'))
    expect(within(again.drawer).getByLabelText('detail.specs.oilViscosity')).toHaveValue('0W-20')
  })

  it('guard: save, flip units while closed, reopen: the saved value in the new unit', async () => {
    flipToMetric()
    mockedUpdate.mockResolvedValue({ ...vehicle, oil_capacity_liters: '9.4635' } as Vehicle)
    render(<Host />)
    const first = await openOil()
    fireEvent.change(first.oil, { target: { value: '9.4635' } })
    fireEvent.click(within(first.drawer).getByRole('button', { name: 'common:save' }))
    await waitFor(() => expect(mockedUpdate).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())

    flipToImperial()
    const again = await openOil()

    expect(within(again.drawer).getByText(/detail\.specs\.oilCapacityWithUnit \(qt/)).toBeInTheDocument()
    // 9.4635 L / 0.946352946 = 10.0 US qt.
    await waitFor(() => expect(again.oil.value).toBe('10.0'))
  })
})
