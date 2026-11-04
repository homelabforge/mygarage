/**
 * The vehicle's odometer unit, set in the edit drawer (#172).
 *
 * Its own file because the "Account default (km)" label interpolates the
 * ACCOUNT's unit, which the global i18n mock (`t: key => key`) discards, and
 * the drawer's main suite asserts bare keys everywhere else. The drawer is
 * mounted inside VehicleDetail's scope, so the scoped hook here reads miles
 * while the account reads kilometres: the label must name the account's.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { ReactNode } from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import type { Vehicle, VehicleDetailStats } from '../../../types/vehicle'

vi.mock('../../../services/api', () => ({
  default: { get: vi.fn(), put: vi.fn().mockResolvedValue({ data: {} }) },
}))
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }))
vi.mock('../../../hooks/useUnitPreference', async () => {
  const { METRIC_UNITS } = await import('@/__tests__/factories')
  return {
    useUnitPreference: () => ({
      system: 'metric',
      showBoth: false,
      units: { ...METRIC_UNITS, distance: 'mi', speed: 'mph' },
    }),
    useAccountUnitPreference: () => ({ system: 'metric', showBoth: false, units: METRIC_UNITS }),
  }
})
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: { unit?: string }) =>
      options?.unit !== undefined ? `${key} (${options.unit})` : key,
    i18n: { language: 'en', changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children: ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: () => {} },
}))

import api from '../../../services/api'
import VehicleEditDrawer from '../VehicleEditDrawer'
import { makeDetailStats } from '../../../__tests__/factories'

const mockedApi = vi.mocked(api)

const baseVehicle: Vehicle = {
  vin: 'TEST12345678901234',
  identifier_type: 'vin',
  has_vin: true,
  nickname: 'Test Car',
  vehicle_type: 'Car',
  usage_unit: 'distance',
  secondary_usage_enabled: false,
  created_at: '2024-01-15T00:00:00Z',
  archived_visible: true,
  fuel_type: 'gasoline',
  location_tracking_enabled: true,
  distance_unit: null,
  wheel_layout: null,
  effective_wheel_layout: 'four',
  default_wheel_layout: 'four',
}

const stats = (usage_unit: VehicleDetailStats['usage_unit']): VehicleDetailStats =>
  makeDetailStats({ usage_unit, spent_this_year: '0', year: 2024 })

function renderDrawer(vehicle: Vehicle): void {
  mockedApi.get.mockImplementation((url: string) =>
    Promise.resolve({ data: url.includes('detail-stats') ? stats(vehicle.usage_unit) : vehicle })
  )
  render(
    <MemoryRouter>
      <VehicleEditDrawer
        open
        vin={vehicle.vin}
        vehicle={vehicle}
        onClose={vi.fn()}
        onUpdated={vi.fn()}
        onDownloadWindowSticker={vi.fn()}
        onUploadWindowSticker={vi.fn()}
        onManageTorqueSources={vi.fn()}
      />
    </MemoryRouter>,
  )
}

beforeEach(() => vi.clearAllMocks())

describe("VehicleEditDrawer: the vehicle's odometer unit", () => {
  it('is offered for a distance vehicle, with the account unit named on Account default', async () => {
    renderDrawer(baseVehicle)

    const select = (await screen.findByLabelText('edit.distanceUnit')) as HTMLSelectElement
    const options = Array.from(select.options).map((o) => [o.value, o.textContent])
    expect(options).toEqual([
      ['', 'edit.distanceUnitAccountDefault (km)'],
      ['km', 'edit.distanceUnitKm'],
      ['mi', 'edit.distanceUnitMi'],
    ])
    expect(select.value).toBe('')
  })

  it('is not offered for a vehicle that tracks hours only', async () => {
    renderDrawer({ ...baseVehicle, usage_unit: 'hours' })

    await screen.findByLabelText('edit.fuelType')
    expect(screen.queryByLabelText('edit.distanceUnit')).not.toBeInTheDocument()
  })

  it('seeds the stored unit, and Account default submits null (not an empty string)', async () => {
    renderDrawer({ ...baseVehicle, distance_unit: 'mi' })

    const select = (await screen.findByLabelText('edit.distanceUnit')) as HTMLSelectElement
    await waitFor(() => expect(select.value).toBe('mi'))
    fireEvent.change(select, { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: 'edit.saveChanges' }))

    await waitFor(() => expect(mockedApi.put).toHaveBeenCalled())
    const [, payload] = mockedApi.put.mock.calls[0]
    expect(payload).toMatchObject({ distance_unit: null })
  })

  it('submits a chosen unit', async () => {
    renderDrawer(baseVehicle)

    const select = (await screen.findByLabelText('edit.distanceUnit')) as HTMLSelectElement
    fireEvent.change(select, { target: { value: 'mi' } })
    fireEvent.click(screen.getByRole('button', { name: 'edit.saveChanges' }))

    await waitFor(() => expect(mockedApi.put).toHaveBeenCalled())
    expect(mockedApi.put.mock.calls[0][1]).toMatchObject({ distance_unit: 'mi' })
  })
})
