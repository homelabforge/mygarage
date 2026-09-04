import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { ReactNode } from 'react'
import { render, screen, cleanup } from '../../../__tests__/test-utils'
import { fireEvent } from '@testing-library/react'
import type { DriveSession, DriveSessionListResponse } from '../../../types/livelink'
import { binarySystemFor, presetUnitsFor, type UnitSet } from '../../../types/units'
import vehiclesEn from '../../../locales/en/vehicles.json'

// ─────────────────────────────────────────────────────────────────────────────
// Harness note (mirrors the Task-1/Task-2 LiveLink precedent — assertions and
// fixtures are exactly the brief's; only the i18n mock is overridden locally):
//
// `fetchSessions` lists `t` in its `useCallback` deps and the mount effect
// depends on `fetchSessions`. The GLOBAL react-i18next mock (src/__tests__/
// setup.ts) returns a FRESH `t` on every render, so `fetchSessions` is a new
// reference every render and `useEffect([fetchSessions])` re-fires after each
// data-commit re-render — a runaway refetch loop that makes the exact
// `getSessions.mock.calls` array this suite asserts (`[['V1', { limit: 50 }]]`)
// impossible. Real react-i18next memoizes `t`, so this loop is a TEST artifact,
// never a production behaviour. We override the mock LOCALLY with a STABLE
// module-level `t` (same key-echo shape as the global mock) so `fetchSessions`
// is stable across renders — the fetch fires exactly once, as in production.
// This is a TEST-harness fix only; the component's fetch/effect logic is
// unchanged (reskin = rendering-only).
// ─────────────────────────────────────────────────────────────────────────────
//
// The `t` below resolves ONE key from the SHIPPED English bundle:
// `vehicles:livelink.unknownUnit`. That key's value is the entire
// user-visible wording of the L6 affordance, and a key-echoing mock would let
// the wording change without a test noticing. Every other key still echoes, so
// the existing key-name assertions are untouched.
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

const getSessions = vi.fn()
vi.mock('@/services/livelinkService', () => ({
  livelinkService: { getSessions: (vin: string, params: unknown) => getSessions(vin, params) },
}))
// The tab reads `useUnitFormat()`, which is left REAL so the rendered strings
// come from the shared adapter table rather than from a stub. Only the resolved
// set underneath it is swapped, per test.
// `system` is DERIVED from `units` exactly as the real hook derives it. Pinning
// it to a literal would let the custom-set case pass for the wrong reason: the
// defect being pinned is that `system` (collapsed from VOLUME) disagrees with
// the per-quantity tokens, and a hardcoded `system` cannot express that.
let units: UnitSet = presetUnitsFor('imperial', 'us')
vi.mock('@/hooks/useUnitPreference', () => ({
  useUnitPreference: () => ({
    system: binarySystemFor(units.volume),
    showBoth: false,
    units,
    gallonStandard: units.secondary_gallon,
  }),
}))
vi.mock('@/hooks/useTimeFormat', () => ({ useTimeFormat: () => ({ timeFormat: '12h' }) }))
vi.mock('@/constants/i18n', () => ({ getActiveLocale: () => 'en-US' }))
vi.mock('@/utils/parseAPITimestamp', () => ({ formatAPITimestamp: () => 'Sun, Jul 26', formatTime: () => '12:00' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import LiveLinkSessionsTab from '../LiveLinkSessionsTab'

// M1: contract-valid typed builders (`satisfies DriveSession`, all required fields incl. `vin`/
// `device_id`/`created_at`). M3: an ENDED session (ended_at set → no in-progress chip) AND an
// IN-PROGRESS session (ended_at null → isActive → the `<Chip tone="success">` renders).
const endedSession = {
  id: 5, vin: 'V1', device_id: 'DEV1', created_at: 'x',
  started_at: 'x', ended_at: 'x', duration_seconds: 3600, distance_km: 100,
  max_speed: 60, avg_speed: 40, avg_rpm: 2000, max_rpm: 4000,
  avg_coolant_temp: 90, max_coolant_temp: 95, start_odometer: 1000, end_odometer: 1100,
  // Cut by the movement rule, so the "Earlier detection" chip stays off unless
  // a test explicitly asks for a legacy row.
  boundary_algorithm_version: 1,
} satisfies DriveSession
const inProgressSession = { ...endedSession, id: 6, ended_at: null } satisfies DriveSession
const list = (over: Partial<DriveSessionListResponse> = {}) =>
  ({ sessions: [endedSession], total: 1, stationary_total: 0, ...over }) satisfies DriveSessionListResponse

beforeEach(() => {
  vi.clearAllMocks()
  units = presetUnitsFor('imperial', 'us')
  getSessions.mockResolvedValue(list())
})

describe('LiveLinkSessionsTab', () => {
  it('renders the session figures via the component formatters and calls getSessions(vin, {limit:50}) (fails if the list, a formatter, or the fetch args break)', async () => {
    render(<LiveLinkSessionsTab vin="V1" />)
    expect(await screen.findByText('1h 0m')).toBeInTheDocument() // formatDuration(3600)
    // distance_km is genuinely kilometres now: the backend converts a custom-PID
    // odometer with the device's declared odometer_unit before storing it, so the
    // reader's own unit can be claimed for it again.
    expect(screen.getByText('62 mi')).toBeInTheDocument()
    expect(screen.getByText('37 mph')).toBeInTheDocument()         // 60 km/h / 1.60934, at 0 dp
    expect(getSessions.mock.calls).toStrictEqual([['V1', { limit: 50, include_stationary: false }]])
  })

  // ───────────────────────────────────────────────────────────────────────────
  // Hiding drives the old rule invented.
  //
  // Sessions used to open whenever the dongle reached the broker, and a parked
  // WiCAN checks in about every 95 minutes. On the instance this was built
  // against, 2,921 of 3,262 recorded sessions never moved at all. They cannot
  // be rebuilt (the telemetry was never captured) and must not be deleted (a
  // release that tried removed 2,700 km of real distance), so the list hides
  // them by default and says so.
  //
  // The filter is MOVEMENT, not `boundary_algorithm_version`: 341 of that same
  // history are pre-v3.3.0 sessions in which the vehicle really did move.
  // ───────────────────────────────────────────────────────────────────────────

  it('asks the API to leave out sessions in which nothing moved, by default', async () => {
    render(<LiveLinkSessionsTab vin="V1" />)
    await screen.findByText('1h 0m')
    expect(getSessions).toHaveBeenCalledWith('V1', { limit: 50, include_stationary: false })
  })

  it('explains an empty list rather than looking broken when drives are hidden', async () => {
    // The upgrade case: every drive on record predates movement detection, so
    // the default view is legitimately empty. An unexplained blank page here is
    // indistinguishable from a failure, and this is the state every existing
    // instance lands in on the day it upgrades.
    getSessions.mockResolvedValue(list({ sessions: [], total: 0, stationary_total: 2921 }))
    render(<LiveLinkSessionsTab vin="V1" />)

    expect(await screen.findByText('livelink.sessions.stationaryHiddenTitle')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'livelink.sessions.showStationary' })).toBeInTheDocument()
  })

  it('keeps the ordinary empty state when there is nothing hidden either', async () => {
    // A genuinely new instance has no drives and nothing to explain. Offering
    // to reveal 0 hidden drives would be nonsense.
    getSessions.mockResolvedValue(list({ sessions: [], total: 0, stationary_total: 0 }))
    render(<LiveLinkSessionsTab vin="V1" />)

    expect(await screen.findByText('livelink.sessions.noRecords')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'livelink.sessions.showStationary' })).toBeNull()
  })

  it('refetches with the old drives included when asked, and can put them back', async () => {
    getSessions.mockResolvedValue(list({ sessions: [], total: 0, stationary_total: 2921 }))
    render(<LiveLinkSessionsTab vin="V1" />)

    fireEvent.click(await screen.findByRole('button', { name: 'livelink.sessions.showStationary' }))

    await vi.waitFor(() =>
      expect(getSessions).toHaveBeenLastCalledWith('V1', { limit: 50, include_stationary: true })
    )
  })

  it('marks a drive the old rule recorded, so a revealed row says what it is', async () => {
    const legacyRow = { ...endedSession, id: 9, boundary_algorithm_version: 0 }
    const modernRow = { ...endedSession, id: 10, boundary_algorithm_version: 1 }
    getSessions.mockResolvedValue(
      list({ sessions: [legacyRow, modernRow], total: 2, stationary_total: 1 })
    )
    render(<LiveLinkSessionsTab vin="V1" />)

    await screen.findAllByText('1h 0m')
    expect(screen.getAllByText('livelink.sessions.legacyBadge')).toHaveLength(1)
  })

  it('shows the in-progress chip only for an active (unended) session — both ways (fails if the isActive marker is dropped or shown unconditionally)', async () => {
    render(<LiveLinkSessionsTab vin="V1" />) // default = endedSession (ended_at set)
    await screen.findByText('1h 0m')
    expect(screen.queryByText('livelink.sessions.inProgress')).not.toBeInTheDocument()
    cleanup()

    getSessions.mockResolvedValue(list({ sessions: [inProgressSession] }))
    render(<LiveLinkSessionsTab vin="V1" />)
    expect(await screen.findByText('livelink.sessions.inProgress')).toBeInTheDocument()
  })

  it('expands and collapses the detail grid on toggle — both ways (fails if the expand toggle is unwired)', async () => {
    render(<LiveLinkSessionsTab vin="V1" />)
    await screen.findByText('1h 0m')
    // the expanded Tile label is absent when collapsed
    expect(screen.queryByText('livelink.sessions.duration')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button')) // the only button is the card header toggle
    expect(screen.getByText('livelink.sessions.duration')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button'))
    expect(screen.queryByText('livelink.sessions.duration')).not.toBeInTheDocument()
  })

  it('renders the odometer pair in the reader\'s units and coolant through the adapter', async () => {
    render(<LiveLinkSessionsTab vin="V1" />)
    await screen.findByText('1h 0m')
    fireEvent.click(screen.getByRole('button'))
    // start_odometer / end_odometer are stored canonical km like the delta, so
    // both are labelled in the reader's own unit.
    expect(screen.getByText('621 mi \u2192 684 mi')).toBeInTheDocument()
    // 90 C x 9/5 + 32 = 194, at the f adapter's 1 dp. It read "194\u00b0F" before.
    expect(screen.getByText('194.0 \u00b0F / 203.0 \u00b0F')).toBeInTheDocument()
  })

  it('groups RPM in the active locale and treats zero as a reading, not as absent', async () => {
    // RPM is outside the unit system, but it is still a NUMBER a reader reads:
    // `toFixed(0)` is locale-blind, so this tile said "2000" while the LiveLink
    // gauge for the same reading said "2,000". That half is the fix.
    //
    // The zero half is a PIN, not a fix, and the distinction is deliberate: the
    // old `avg_rpm?.toFixed(0) || '--'` looks like it swallows a genuine 0 and
    // does not, because `(0)?.toFixed(0)` is the truthy string "0". Verified
    // rather than assumed. It is pinned so that a later `value ? ... : '--'`,
    // which WOULD swallow it, cannot land silently.
    render(<LiveLinkSessionsTab vin="V1" />)
    await screen.findByText('1h 0m')
    fireEvent.click(screen.getByRole('button'))
    expect(screen.getByText('2,000 / 4,000')).toBeInTheDocument()
    cleanup()

    getSessions.mockResolvedValue(list({ sessions: [{ ...endedSession, avg_rpm: 0 }] }))
    render(<LiveLinkSessionsTab vin="V1" />)
    await screen.findByText('1h 0m')
    fireEvent.click(screen.getByRole('button'))
    expect(screen.getByText('0 / 4,000')).toBeInTheDocument()
  })

  it('answers PER QUANTITY for a custom set, where the binary system would say metric', async () => {
    // Spec D8 collapses `system` from VOLUME, so this client reads 'metric' and
    // every `system === 'imperial'` branch answers no, while the user has in
    // fact chosen mph and \u00b0F. Before the adapter, this rendered km/h and \u00b0C.
    units = { ...presetUnitsFor('metric', 'us'), speed: 'mph', temperature: 'f' }
    render(<LiveLinkSessionsTab vin="V1" />)
    await screen.findByText('1h 0m')
    expect(screen.getByText('37 mph')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button'))
    expect(screen.getByText('194.0 \u00b0F / 203.0 \u00b0F')).toBeInTheDocument()
  })

  it('renders the distance in the reader\'s own unit set', async () => {
    units = presetUnitsFor('metric', 'us')
    render(<LiveLinkSessionsTab vin="V1" />)
    await screen.findByText('1h 0m')
    // The stored value is canonical km, so a metric reader sees it unconverted
    // and an imperial reader sees 62 mi. One number, two honest renderings.
    expect(screen.getByText('100 km')).toBeInTheDocument()
    expect(screen.queryByText('100 (unknown unit)')).not.toBeInTheDocument()
  })

  it('labels a present odometer and leaves an absent one as the absent marker', async () => {
    getSessions.mockResolvedValue(
      list({ sessions: [{ ...endedSession, distance_km: null, end_odometer: null }] }),
    )
    render(<LiveLinkSessionsTab vin="V1" />)
    await screen.findByText('1h 0m')
    fireEvent.click(screen.getByRole('button'))
    // The absent half must stay the absent marker, not acquire a unit label.
    expect(screen.getByText('621 mi \u2192 --')).toBeInTheDocument()
    expect(screen.getByText('--')).toBeInTheDocument() // the Distance tile
  })

  it('shows the empty state when there are no sessions (fails if the empty branch is dropped)', async () => {
    getSessions.mockResolvedValue(list({ sessions: [], total: 0 }))
    render(<LiveLinkSessionsTab vin="V1" />)
    expect(await screen.findByText('livelink.sessions.noRecords')).toBeInTheDocument()
  })
})
