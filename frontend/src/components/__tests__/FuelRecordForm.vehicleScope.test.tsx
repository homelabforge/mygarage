/**
 * The reporter's own path (#172): a fill-up on a mi vehicle from a km account,
 * through the REAL `useUnitPreference`. Only `AuthContext` and the API are
 * mocked, so the vehicle scope is what puts the odometer in miles while the
 * volume stays in the account's litres.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { ReactNode } from 'react'
import { screen, waitFor, fireEvent } from '@testing-library/react'
import { render } from '../../__tests__/test-utils'
import { METRIC_UNITS } from '../../__tests__/factories'
import { VehicleUnitScope } from '../../contexts/VehicleUnitScope'
import FuelRecordForm from '../FuelRecordForm'
import type { Vehicle } from '../../types/vehicle'

const mockedApiGet = vi.fn()
const mockedApiPost = vi.fn().mockResolvedValue({ data: {} })
vi.mock('../../services/api', () => ({
  default: {
    get: (...args: unknown[]) => mockedApiGet(...args),
    post: (...args: unknown[]) => mockedApiPost(...args),
    put: vi.fn().mockResolvedValue({ data: {} }),
  },
}))
vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({
    user: { unit_preference: 'metric', show_both_units: false, resolved_units: METRIC_UNITS },
    isAuthenticated: true,
    defaultUnitPrefs: null,
  }),
}))
vi.mock('../../hooks/useTimeFormat', () => ({ useTimeFormat: () => ({ timeFormat: '24h' }) }))
// Retains the interpolated unit, which the global `t: (key) => key` discards.
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: { unit?: string }) =>
      options?.unit ? `${key} (${options.unit})` : key,
    i18n: { language: 'en', changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children: ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: () => {} },
}))

const VIN = 'TEST12345678901234'
const vehicle = {
  vin: VIN,
  nickname: 'Test Car',
  vehicle_type: 'Car',
  created_at: '2024-01-15T00:00:00Z',
  archived_visible: true,
  fuel_type: 'gasoline',
  usage_unit: 'distance',
  secondary_usage_enabled: false,
  location_tracking_enabled: true,
  distance_unit: 'mi',
} as Vehicle

const field = (id: string): HTMLInputElement => document.getElementById(id) as HTMLInputElement
const labelText = (id: string): string =>
  document.querySelector(`label[for="${id}"]`)?.textContent ?? ''

beforeEach(() => {
  vi.clearAllMocks()
  mockedApiGet.mockImplementation((url: string) =>
    url.includes('/settings/public')
      ? Promise.resolve({ data: { settings: [] } })
      : Promise.resolve({ data: vehicle })
  )
  mockedApiPost.mockResolvedValue({ data: {} })
})

describe('FuelRecordForm inside a mi vehicle on a km account', () => {
  it('reads the odometer in miles and the volume in litres, and stores km', async () => {
    render(
      <VehicleUnitScope distanceUnit="mi">
        <FuelRecordForm vin={VIN} onClose={vi.fn()} onSuccess={vi.fn()} />
      </VehicleUnitScope>,
    )
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())

    expect(labelText('odometer_km')).toBe('common:mileage * (mi)')
    expect(labelText('liters')).toBe('fuel.volume (L)')

    fireEvent.change(field('date'), { target: { value: '2026-02-10' } })
    fireEvent.change(field('odometer_km'), { target: { value: '50000' } })
    fireEvent.change(field('price_basis'), { target: { value: 'per_volume' } })
    fireEvent.change(field('liters'), { target: { value: '40' } })
    fireEvent.submit(screen.getByRole('dialog').querySelector('form') as HTMLFormElement)

    await waitFor(() => expect(mockedApiPost).toHaveBeenCalled())
    const call = mockedApiPost.mock.calls.find((c) => typeof c[0] === 'string' && c[0].endsWith('/fuel'))
    expect(call, 'no create POST was made').toBeDefined()
    const payload = call![1] as Record<string, unknown>
    // 50000 mi x 1.609344 = 80467.2 km; the litres pass through.
    expect(payload.odometer_km).toBe(80467.2)
    expect(payload.liters).toBe(40)
  })
})
