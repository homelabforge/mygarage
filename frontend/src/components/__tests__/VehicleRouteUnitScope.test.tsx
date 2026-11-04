/**
 * The analytics route is not VehicleDetail, so a wrapper scopes it to the
 * vehicle's odometer unit (#172). It is display only, so every failure path is
 * safe: the cached copy, else the account's units.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { METRIC_UNITS } from '../../__tests__/factories'

const getVehicle = vi.fn()
vi.mock('../../services/vehicleService', () => ({
  default: { get: (...args: unknown[]) => getVehicle(...args) },
}))
vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({
    user: { unit_preference: 'metric', show_both_units: false, resolved_units: METRIC_UNITS },
    isAuthenticated: true,
    defaultUnitPrefs: null,
  }),
}))

import VehicleRouteUnitScope from '../VehicleRouteUnitScope'
import { useUnitPreference } from '../../hooks/useUnitPreference'
import { rememberVehicle } from '../../utils/vehicleCache'
import type { Vehicle } from '../../types/vehicle'

function Probe() {
  return <p data-testid="unit">{useUnitPreference().units.distance}</p>
}

function renderRoute() {
  return render(
    <MemoryRouter initialEntries={['/vehicles/V1/analytics']}>
      <Routes>
        <Route
          path="/vehicles/:vin/analytics"
          element={
            <VehicleRouteUnitScope>
              <Probe />
            </VehicleRouteUnitScope>
          }
        />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
})

describe('VehicleRouteUnitScope', () => {
  it('shows a spinner, then renders in the fetched vehicle unit', async () => {
    getVehicle.mockResolvedValue({ vin: 'V1', distance_unit: 'mi' })
    renderRoute()
    expect(screen.getByRole('status')).toBeInTheDocument()
    expect(await screen.findByTestId('unit')).toHaveTextContent('mi')
  })

  it('falls back to the cached vehicle when the fetch fails', async () => {
    getVehicle.mockRejectedValue(new Error('offline'))
    rememberVehicle('V1', { vin: 'V1', distance_unit: 'mi' } as Vehicle)
    renderRoute()
    expect(await screen.findByTestId('unit')).toHaveTextContent('mi')
  })

  it('renders in the account units when there is neither vehicle nor cache', async () => {
    getVehicle.mockRejectedValue(new Error('offline'))
    renderRoute()
    await waitFor(() => expect(screen.getByTestId('unit')).toHaveTextContent('km'))
  })
})
