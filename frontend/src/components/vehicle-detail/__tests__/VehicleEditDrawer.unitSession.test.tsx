/**
 * The vehicle edit drawer pins the account set for each open (R4).
 *
 * It stays mounted while closed, so the pin has to be taken on every open,
 * not once at mount. The REAL `useUnitPreference` runs; only `AuthContext` and
 * the API are mocked. On main a units flip mid-edit relabels the DEF capacity
 * and converts the typed gallons as litres.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { ReactElement, ReactNode } from 'react'
import { act, render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import type { Vehicle } from '../../../types/vehicle'
import type { UnitSet } from '../../../types/units'
import { IMPERIAL_UNITS, METRIC_UNITS, makeDetailStats } from '../../../__tests__/factories'
import { setUnitPrefs } from '../../../utils/unitPrefsStore'

const h = vi.hoisted(() => ({ defaultUnitPrefs: null as UnitSet | null }))

vi.mock('../../../services/api', () => ({
  default: { get: vi.fn(), put: vi.fn().mockResolvedValue({ data: {} }) },
}))
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }))
vi.mock('../../../contexts/AuthContext', () => ({
  useAuth: () => ({ user: null, isAuthenticated: false, defaultUnitPrefs: h.defaultUnitPrefs }),
}))
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

const mockedApi = vi.mocked(api)

// 37.854 L is 10 US gal.
const vehicle: Vehicle = {
  vin: 'TEST12345678901234',
  nickname: 'Test Truck',
  vehicle_type: 'Truck',
  usage_unit: 'distance',
  secondary_usage_enabled: false,
  created_at: '2024-01-15T00:00:00Z',
  archived_visible: true,
  fuel_type: 'diesel',
  location_tracking_enabled: true,
  distance_unit: null,
  def_tank_capacity_liters: '37.854',
}

const drawer = (open: boolean): ReactElement => (
  <MemoryRouter>
    <VehicleEditDrawer
      open={open}
      vin={vehicle.vin}
      vehicle={vehicle}
      onClose={vi.fn()}
      onUpdated={vi.fn()}
      onDownloadWindowSticker={vi.fn()}
      onUploadWindowSticker={vi.fn()}
      onManageTorqueSources={vi.fn()}
    />
  </MemoryRouter>
)

const capacityLabel = (): string =>
  document.querySelector('label[for="def_tank_capacity_liters"]')?.textContent ?? ''
const capacity = (): HTMLInputElement =>
  document.getElementById('def_tank_capacity_liters') as HTMLInputElement
const accountDefault = async (): Promise<string> => {
  const select = (await screen.findByLabelText('edit.distanceUnit')) as HTMLSelectElement
  return select.options[0].textContent ?? ''
}

const flipToMetric = (): void =>
  act(() => setUnitPrefs({ units: METRIC_UNITS, unit_preference: null, show_both_units: false }))

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  // Bare event: the store re-reads everything, so it drops the last test's set.
  window.dispatchEvent(new Event('storage'))
  h.defaultUnitPrefs = METRIC_UNITS
  setUnitPrefs({ units: IMPERIAL_UNITS, unit_preference: null, show_both_units: false })
  mockedApi.get.mockImplementation((url: string) =>
    Promise.resolve({
      data: url.includes('detail-stats') ? makeDetailStats({ usage_unit: 'distance' }) : vehicle,
    }),
  )
  mockedApi.put.mockResolvedValue({ data: vehicle })
})

describe('VehicleEditDrawer holds the account units while open', () => {
  it('a flip to metric mid-edit keeps gal and stores the typed gallons', async () => {
    render(drawer(true))
    await waitFor(() => expect(capacity().value).toBe('10'))
    expect(capacityLabel()).toMatch(/\(gal\)/)

    flipToMetric()

    expect(capacityLabel()).toMatch(/\(gal\)/)
    expect(await accountDefault()).toBe('edit.distanceUnitAccountDefault (mi)')
    fireEvent.change(capacity(), { target: { value: '5' } })
    fireEvent.click(screen.getByRole('button', { name: 'edit.saveChanges' }))
    await waitFor(() => expect(mockedApi.put).toHaveBeenCalled())
    // 5 x 3.785411784 = 18.927 L.
    expect(mockedApi.put.mock.calls[0][1]).toMatchObject({ def_tank_capacity_liters: 18.927 })
  })

  it('guard: it stays mounted through a close, and the next open takes the new units', async () => {
    const { rerender } = render(drawer(true))
    await waitFor(() => expect(capacity().value).toBe('10'))
    rerender(drawer(false))
    flipToMetric()

    rerender(drawer(true))

    // Reseeded in litres, at the field's two decimals.
    await waitFor(() => expect(capacity().value).toBe('37.85'))
    expect(capacityLabel()).toMatch(/\(L\)/)
    expect(await accountDefault()).toBe('edit.distanceUnitAccountDefault (km)')
  })
})
