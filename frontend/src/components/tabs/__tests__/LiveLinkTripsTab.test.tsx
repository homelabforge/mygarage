import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { ReactNode } from 'react'
import { render, screen, waitFor } from '../../../__tests__/test-utils'
import { fireEvent } from '@testing-library/react'
import type { Trip, TripList, TripPointsResponse } from '../../../types/trips'
import vehiclesEn from '../../../locales/en/vehicles.json'

// ─────────────────────────────────────────────────────────────────────────────
// Harness note (mirrors the merged LiveLink Sessions/Charts precedent —
// assertions and fixtures are exactly the brief's; only the i18n mock is
// overridden locally):
//
// `fetchTrips` AND `fetchTripPoints` both list `t` in their `useCallback` deps,
// and the mount/select effects depend on those callbacks. The GLOBAL
// react-i18next mock (src/__tests__/setup.ts) returns a FRESH `t` on every
// render, so those callbacks are new references every render and their effects
// re-fire after each data-commit re-render — a runaway refetch loop that makes
// the exact `getTrips.mock.calls` / `getTripPoints.mock.calls` arrays this suite
// asserts impossible. Real react-i18next memoizes `t`, so this loop is a TEST
// artifact, never a production behaviour. We override the mock LOCALLY with a
// STABLE module-level `t` (same key-echo shape as the global mock) so the
// callbacks are stable across renders — each fetch fires exactly once, as in
// production. TEST-harness fix only; the component's fetch/effect/[vin, t] deps
// are unchanged (reskin = rendering-only).
// ─────────────────────────────────────────────────────────────────────────────
//
// The `t` below resolves ONE key from the SHIPPED English bundle:
// `vehicles:livelink.unknownUnit`. That key holds the whole user-visible
// wording of the unknown-unit affordance, so a key-echoing mock would let the
// wording change with nothing failing. Every other key still echoes.
vi.mock('react-i18next', () => {
  const t = (key: string) =>
    key === 'vehicles:livelink.unknownUnit' ? vehiclesEn.livelink.unknownUnit : key
  return {
    useTranslation: () => ({
      t,
      i18n: { language: 'en', changeLanguage: () => Promise.resolve() },
    }),
    Trans: ({ children }: { children: ReactNode }) => children,
    initReactI18next: { type: '3rdParty', init: () => {} },
  }
})

const getTrips = vi.fn()
const getTripPoints = vi.fn()
const setLocationTracking = vi.fn()
const vehicleGet = vi.fn()
vi.mock('@/services/livelinkService', () => ({
  livelinkService: {
    getTrips: (vin: string, params: unknown) => getTrips(vin, params),
    getTripPoints: (vin: string, id: number) => getTripPoints(vin, id),
    setLocationTracking: (vin: string, enabled: boolean) => setLocationTracking(vin, enabled),
  },
}))
vi.mock('@/services/vehicleService', () => ({ default: { get: (vin: string) => vehicleGet(vin) } }))
vi.mock('@/hooks/useTimeFormat', () => ({ useTimeFormat: () => ({ timeFormat: '12h' }) }))
vi.mock('@/utils/parseAPITimestamp', () => ({ formatAPITimestamp: () => 'Sun, Jul 26', formatTime: () => '12:00' }))
vi.mock('@/components/maps/TripRouteMap', () => ({ default: () => <div data-testid="trip-route-map" /> }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import LiveLinkTripsTab from '../LiveLinkTripsTab'

// M1: contract-valid typed builders (`satisfies Trip`/`TripPointsResponse`, all required fields — the
// points RESPONSE carries `session_id`, each point carries `id`/`latitude`/`longitude`/`timestamp`).
const trip = {
  session_id: 55, started_at: 'x', ended_at: 'x',
  duration_seconds: 1800, distance_km: 20, point_count: 12,
} satisfies Trip
const list = (over: Partial<TripList> = {}) => ({ trips: [trip], ...over }) satisfies TripList
const points = {
  session_id: 55,
  points: [{ id: 1, latitude: 1, longitude: 2, timestamp: 'x' }],
} satisfies TripPointsResponse

beforeEach(() => {
  vi.clearAllMocks()
  getTrips.mockResolvedValue(list())
  vehicleGet.mockResolvedValue({ location_tracking_enabled: false })
  setLocationTracking.mockResolvedValue({ location_tracking_enabled: true })
  getTripPoints.mockResolvedValue(points)
})

describe('LiveLinkTripsTab', () => {
  it('fetches the initial trips + tracking state with exact args (M1)', async () => {
    render(<LiveLinkTripsTab vin="V1" />)
    await waitFor(() => expect(getTrips.mock.calls).toStrictEqual([['V1', { limit: 50 }]]))
    expect(vehicleGet.mock.calls).toStrictEqual([['V1']])
  })

  it('selecting a trip toggles aria-pressed, fetches points and mounts the map; re-clicking deselects and unmounts it (M5: false→true→false)', async () => {
    render(<LiveLinkTripsTab vin="V1" />)
    const card = await screen.findByRole('button', { name: /Sun, Jul 26/ })
    expect(card).toHaveAttribute('aria-pressed', 'false')
    expect(screen.queryByTestId('trip-route-map')).not.toBeInTheDocument()

    fireEvent.click(card)
    await waitFor(() => expect(getTripPoints.mock.calls).toStrictEqual([['V1', 55]]))
    expect(card).toHaveAttribute('aria-pressed', 'true')
    expect(await screen.findByTestId('trip-route-map')).toBeInTheDocument()

    fireEvent.click(card)
    expect(card).toHaveAttribute('aria-pressed', 'false')
    await waitFor(() => expect(screen.queryByTestId('trip-route-map')).not.toBeInTheDocument())
  })

  it('shows the map-empty state when the selected trip has no points (the FALSE state — fails if the empty branch is dropped)', async () => {
    getTripPoints.mockResolvedValue({ session_id: 55, points: [] })
    render(<LiveLinkTripsTab vin="V1" />)
    fireEvent.click(await screen.findByRole('button', { name: /Sun, Jul 26/ }))
    expect(await screen.findByText('livelink.trips.mapEmpty')).toBeInTheDocument()
    expect(screen.queryByTestId('trip-route-map')).not.toBeInTheDocument()
  })

  it('toggling from initial OFF calls setLocationTracking(V1, true) (M5: false→true)', async () => {
    vehicleGet.mockResolvedValue({ location_tracking_enabled: false })
    setLocationTracking.mockResolvedValue({ location_tracking_enabled: true })
    render(<LiveLinkTripsTab vin="V1" />)
    const toggle = await screen.findByRole('checkbox', { name: 'livelink.trips.locationTracking' })
    await waitFor(() => expect(toggle).toBeEnabled()) // enabled once the tracking state (false) loads
    fireEvent.click(toggle)
    await waitFor(() => expect(setLocationTracking.mock.calls).toStrictEqual([['V1', true]]))
  })

  it('toggling from initial ON calls setLocationTracking(V1, false) (M5: true→false)', async () => {
    vehicleGet.mockResolvedValue({ location_tracking_enabled: true })
    setLocationTracking.mockResolvedValue({ location_tracking_enabled: false })
    render(<LiveLinkTripsTab vin="V1" />)
    const toggle = await screen.findByRole('checkbox', { name: 'livelink.trips.locationTracking' })
    await waitFor(() => expect(toggle).toBeEnabled()) // enabled once the tracking state (true) loads
    fireEvent.click(toggle)
    await waitFor(() => expect(setLocationTracking.mock.calls).toStrictEqual([['V1', false]]))
  })

  it('marks the trip distance unverified instead of formatting it as canonical km', async () => {
    // `Trip.distance_km` is `DriveSession.distance_km` verbatim
    // (`location_service.py::get_trips`), so it is the SAME column the Sessions
    // tab reads and carries the same custom-PID ambiguity. This tab used to
    // send it through `UnitFormatter.formatDistance`, which treats its argument
    // as canonical kilometres and converted it a second time for an imperial
    // client, while the Sessions tab, on the same number, only relabelled it.
    render(<LiveLinkTripsTab vin="V1" />)
    expect(await screen.findByText('20 (unknown unit)')).toBeInTheDocument()
    expect(screen.queryByText('20 mi')).not.toBeInTheDocument()
  })

  it('renders the absent marker for a trip with no recorded distance', async () => {
    getTrips.mockResolvedValue(list({ trips: [{ ...trip, distance_km: null }] }))
    render(<LiveLinkTripsTab vin="V1" />)
    await screen.findByRole('button', { name: /Sun, Jul 26/ })
    expect(screen.getByText('--')).toBeInTheDocument()
    expect(screen.queryByText(/unknown unit/)).not.toBeInTheDocument()
  })

  it('shows the no-trips empty state when there are no trips', async () => {
    getTrips.mockResolvedValue(list({ trips: [] }))
    render(<LiveLinkTripsTab vin="V1" />)
    expect(await screen.findByText('livelink.trips.noRecords')).toBeInTheDocument()
  })
})
