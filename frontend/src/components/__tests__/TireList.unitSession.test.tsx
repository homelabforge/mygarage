/**
 * TireList's drawers hold the units they opened with; the cards behind them
 * don't (R4).
 *
 * The REAL `useUnitPreference` runs on an anonymous client; the store flips
 * the account from US units to metric while a drawer holds typed text. On
 * main the drawer relabels and the typed psi and miles go out as kPa and km.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { ReactNode } from 'react'
import { act, render, screen, fireEvent } from '@testing-library/react'
import { IMPERIAL_UNITS, METRIC_UNITS } from '../../__tests__/factories'
import { setUnitPrefs } from '../../utils/unitPrefsStore'

const h = vi.hoisted(() => ({ mutate: vi.fn() }))

vi.mock('../../hooks/queries/useTires', () => {
  const mutation = () => ({ mutate: h.mutate, isPending: false })
  return {
    useTires: () => ({
      data: { tires: [TIRE], total: 1, tracks_distance: true, tracks_hours: false },
      isLoading: false,
      error: null,
    }),
    useTireSets: () => ({ data: { sets: [], total: 0 }, isLoading: false, error: null }),
    useCreateAndMountTire: mutation,
    useCreateTire: mutation,
    useUpdateTire: mutation,
    useMountTire: mutation,
    useDismountTire: mutation,
    useRestoreTire: mutation,
    useRetireTire: mutation,
    useRotateTires: mutation,
    useAddTireReading: mutation,
    useDeleteTire: mutation,
    useDeleteTireReading: mutation,
    useCreateTireSet: mutation,
    useUpdateTireSet: mutation,
    useDeleteTireSet: mutation,
    useMountTireSet: mutation,
  }
})
vi.mock('../../hooks/queries/useOdometerRecords', () => ({
  useNearestOdometer: () => ({ data: undefined, isSuccess: false }),
}))
vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}))
vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({ user: null, isAuthenticated: false, defaultUnitPrefs: METRIC_UNITS }),
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
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

const TIRE = vi.hoisted(() => ({
  id: 1,
  vin: '1HGCM82633A004352',
  position: 'FL' as const,
  brand: 'Michelin',
  tread_depth_mm: '7.50',
  pressure_kpa: '240.00',
  min_tread_mm: '3.00',
  below_threshold: false,
  readings: [],
  mount_periods: [],
}))

import TireList from '../TireList'

const labelOf = (id: string): string => document.querySelector(`label[for="${id}"]`)?.textContent ?? ''
const flipToMetric = (): void =>
  act(() => setUnitPrefs({ units: METRIC_UNITS, unit_preference: null, show_both_units: false }))

beforeEach(() => {
  h.mutate.mockReset()
  localStorage.clear()
  // Bare event: the store re-reads everything, so it drops the last test's set.
  window.dispatchEvent(new Event('storage'))
  setUnitPrefs({ units: IMPERIAL_UNITS, unit_preference: null, show_both_units: false })
})

describe('TireList drawers hold their units while open', () => {
  it('a reading keeps psi through a flip, and the card behind repaints', () => {
    render(<TireList vin="1HGCM82633A004352" />)
    fireEvent.click(screen.getByText('tireList.addReading'))
    expect(labelOf('reading-pressure')).toMatch(/\(PSI\)/)
    fireEvent.change(document.getElementById('reading-pressure')!, { target: { value: '36' } })

    flipToMetric()

    expect(labelOf('reading-pressure')).toMatch(/\(PSI\)/)
    // The card behind reads kPa now; the drawer still says psi and 32nds.
    expect(document.body.textContent).toContain('240 kPa')
    expect(labelOf('reading-tread')).toMatch(/\/32 in/)
    fireEvent.click(screen.getByText('common:save'))
    const payload = h.mutate.mock.calls[0][0]
    // 36 psi x 6.894757293168361 = 248.211262554 kPa; the untouched tread keeps 7.5 mm.
    expect(payload.pressure_kpa).toBe(248.211262554)
    expect(payload.tread_depth_mm).toBe(7.5)
  })

  it('a dismount keeps miles through a flip and stores the typed miles', () => {
    render(<TireList vin="1HGCM82633A004352" />)
    fireEvent.click(screen.getAllByText('tireList.dismount')[0])
    fireEvent.change(document.getElementById('dismount-odometer')!, { target: { value: '50000' } })

    flipToMetric()

    expect(labelOf('dismount-odometer')).toMatch(/\(mi\)/)
    fireEvent.click(screen.getAllByText('tireList.dismount').at(-1)!)
    // 50000 mi x 1.609344 = 80467.2 km.
    expect(h.mutate.mock.calls[0][0].dismounted_odometer_km).toBe(80467.2)
  })

  it('a flip while the reading drawer is closed reaches its next open: label, seed and save', () => {
    render(<TireList vin="1HGCM82633A004352" />)
    flipToMetric()

    fireEvent.click(screen.getByText('tireList.addReading'))

    expect(labelOf('reading-pressure')).toMatch(/\(kPa\)/)
    expect(labelOf('reading-tread')).toMatch(/\(mm\)/)
    expect((document.getElementById('reading-pressure') as HTMLInputElement).value).toBe('240')
    fireEvent.change(document.getElementById('reading-pressure')!, { target: { value: '250' } })
    fireEvent.click(screen.getByText('common:save'))
    const payload = h.mutate.mock.calls[0][0]
    // Typed in kPa, stored as kPa; the untouched tread keeps its 7.5 mm.
    expect(payload.pressure_kpa).toBe(250)
    expect(payload.tread_depth_mm).toBe(7.5)
  })
})
