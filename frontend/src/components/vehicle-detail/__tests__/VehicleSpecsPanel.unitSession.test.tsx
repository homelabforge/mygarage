/**
 * The specs editor keeps the units, and the draft, it opened with (R4).
 *
 * The REAL `useUnitPreference` runs on an anonymous client. On main the
 * editor reseeds on any units change, so a flip mid-edit throws away what
 * was typed.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
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
    render(<VehicleSpecsPanel vin="TEST0000000000001" vehicle={vehicle} onUpdated={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'detail.specs.editAria' }))
    const drawer = await screen.findByRole('dialog')
    const oil = within(drawer).getByLabelText('detail.specs.oilCapacityWithUnit') as HTMLInputElement
    fireEvent.change(oil, { target: { value: '12' } })

    act(() => setUnitPrefs({ units: METRIC_UNITS, unit_preference: null, show_both_units: false }))

    expect(oil.value).toBe('12')
    fireEvent.click(within(drawer).getByRole('button', { name: 'common:save' }))
    await waitFor(() => expect(mockedUpdate).toHaveBeenCalledTimes(1))
    // 12 US qt x 0.946352946 = 11.356 L, not 12 L.
    expect(mockedUpdate.mock.calls[0][1].oil_capacity_liters).toBeCloseTo(11.356, 3)
  })
})
