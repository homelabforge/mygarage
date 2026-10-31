/**
 * An open fuel form keeps the units it opened with (R4).
 *
 * The REAL `useUnitPreference` runs here; only `AuthContext` and the API are
 * mocked. The store flips the account from US gallons to litres while the
 * form holds typed text, the way the Settings card in another tab would. On
 * main the labels follow the flip and the typed gallons go out as litres.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { ReactElement, ReactNode } from 'react'
import { act, screen, waitFor, fireEvent } from '@testing-library/react'
import { render } from '../../__tests__/test-utils'
import { IMPERIAL_UNITS, METRIC_UNITS, makeUser, type User } from '../../__tests__/factories'
import type { UnitSet } from '../../types/units'
import { setUnitPrefs } from '../../utils/unitPrefsStore'
import FuelRecordForm from '../FuelRecordForm'
import type { Vehicle } from '../../types/vehicle'

const h = vi.hoisted(() => ({
  user: null as User | null,
  defaultUnitPrefs: null as UnitSet | null,
}))

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
    user: h.user,
    isAuthenticated: h.user !== null,
    defaultUnitPrefs: h.defaultUnitPrefs,
  }),
}))
vi.mock('../../hooks/useTimeFormat', () => ({ useTimeFormat: () => ({ timeFormat: '24h' }) }))
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
} as Vehicle

const field = (id: string): HTMLInputElement => document.getElementById(id) as HTMLInputElement
const labelText = (id: string): string =>
  document.querySelector(`label[for="${id}"]`)?.textContent ?? ''

const form = (): ReactElement => <FuelRecordForm vin={VIN} onClose={vi.fn()} onSuccess={vi.fn()} />

/** Fill in 10 gal at odometer 50000 and submit, then hand back the POST body. */
async function submitTenAt50000(): Promise<Record<string, unknown>> {
  fireEvent.change(field('date'), { target: { value: '2026-02-10' } })
  fireEvent.change(field('odometer_km'), { target: { value: '50000' } })
  fireEvent.change(field('price_basis'), { target: { value: 'per_volume' } })
  fireEvent.change(field('liters'), { target: { value: '10' } })
  fireEvent.submit(screen.getByRole('dialog').querySelector('form') as HTMLFormElement)
  await waitFor(() => expect(mockedApiPost).toHaveBeenCalled())
  const call = mockedApiPost.mock.calls.find((c) => typeof c[0] === 'string' && c[0].endsWith('/fuel'))
  expect(call, 'no create POST was made').toBeDefined()
  return call![1] as Record<string, unknown>
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  // Bare event: the store re-reads everything, so it drops the last test's set.
  window.dispatchEvent(new Event('storage'))
  h.user = null
  h.defaultUnitPrefs = METRIC_UNITS
  mockedApiGet.mockImplementation((url: string) =>
    url.includes('/settings/public')
      ? Promise.resolve({ data: { settings: [] } })
      : Promise.resolve({ data: vehicle }),
  )
  mockedApiPost.mockResolvedValue({ data: {} })
})

describe('FuelRecordForm holds its units while open', () => {
  it('a store flip to litres mid-form leaves the labels in gal and stores the typed gallons', async () => {
    setUnitPrefs({ units: IMPERIAL_UNITS, unit_preference: null, show_both_units: false })
    render(form())
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())
    expect(labelText('liters')).toBe('fuel.volume (gal)')

    // The Settings card in another tab picks metric.
    act(() => setUnitPrefs({ units: METRIC_UNITS, unit_preference: null, show_both_units: false }))

    expect(labelText('liters')).toBe('fuel.volume (gal)')
    expect(labelText('odometer_km')).toBe('common:mileage (mi)')
    const payload = await submitTenAt50000()
    // 10 x 3.785411784 = 37.854 L; 50000 x 1.609344 = 80467.2 km.
    expect(payload.liters).toBe(37.854)
    expect(payload.odometer_km).toBe(80467.2)
  })

  it('an account refresh to metric mid-form does the same on the account rung', async () => {
    h.user = makeUser({ unit_preference: 'imperial', resolved_units: IMPERIAL_UNITS })
    const { rerender } = render(form())
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())
    expect(labelText('liters')).toBe('fuel.volume (gal)')

    h.user = makeUser({ unit_preference: 'metric', resolved_units: METRIC_UNITS })
    rerender(form())

    expect(labelText('liters')).toBe('fuel.volume (gal)')
    const payload = await submitTenAt50000()
    expect(payload.liters).toBe(37.854)
  })

  it('guard: closing and reopening takes the new units', async () => {
    setUnitPrefs({ units: IMPERIAL_UNITS, unit_preference: null, show_both_units: false })
    const { unmount } = render(form())
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())
    act(() => setUnitPrefs({ units: METRIC_UNITS, unit_preference: null, show_both_units: false }))
    unmount()

    render(form())
    expect(labelText('liters')).toBe('fuel.volume (L)')
    expect(labelText('odometer_km')).toBe('common:mileage (km)')
  })
})
