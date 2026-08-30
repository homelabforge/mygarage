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
} satisfies DriveSession
const inProgressSession = { ...endedSession, id: 6, ended_at: null } satisfies DriveSession
const list = (over: Partial<DriveSessionListResponse> = {}) =>
  ({ sessions: [endedSession], total: 1, ...over }) satisfies DriveSessionListResponse

beforeEach(() => {
  vi.clearAllMocks()
  units = presetUnitsFor('imperial', 'us')
  getSessions.mockResolvedValue(list())
})

describe('LiveLinkSessionsTab', () => {
  it('renders the session figures via the component formatters and calls getSessions(vin, {limit:50}) (fails if the list, a formatter, or the fetch args break)', async () => {
    render(<LiveLinkSessionsTab vin="V1" />)
    expect(await screen.findByText('1h 0m')).toBeInTheDocument() // formatDuration(3600)
    // distance_km is filled from a CUSTOM-PID odometer delta, so no unit can be
    // claimed for it. It read "100 mi" before this and the miles were a guess.
    expect(screen.getByText('100 (unknown unit)')).toBeInTheDocument()
    expect(screen.getByText('37 mph')).toBeInTheDocument()         // 60 km/h / 1.60934, at 0 dp
    expect(getSessions.mock.calls).toStrictEqual([['V1', { limit: 50 }]]) // M1: exact call identity
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

  it('marks the odometer pair unverified and renders coolant through the adapter', async () => {
    render(<LiveLinkSessionsTab vin="V1" />)
    await screen.findByText('1h 0m')
    fireEvent.click(screen.getByRole('button'))
    // start_odometer / end_odometer come from the SAME custom-PID query as the
    // distance delta, so neither may be labelled either.
    expect(
      screen.getByText('1,000 (unknown unit) \u2192 1,100 (unknown unit)'),
    ).toBeInTheDocument()
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

  it('renders the same unverified distance under a metric set, claiming nothing either way', async () => {
    units = presetUnitsFor('metric', 'us')
    render(<LiveLinkSessionsTab vin="V1" />)
    await screen.findByText('1h 0m')
    // It read "100 km" here and "100 mi" under imperial: two different claims
    // about one stored number, neither of them checkable.
    expect(screen.getByText('100 (unknown unit)')).toBeInTheDocument()
    expect(screen.queryByText('100 km')).not.toBeInTheDocument()
  })

  it('marks a present odometer and leaves an absent one as the absent marker', async () => {
    getSessions.mockResolvedValue(
      list({ sessions: [{ ...endedSession, distance_km: null, end_odometer: null }] }),
    )
    render(<LiveLinkSessionsTab vin="V1" />)
    await screen.findByText('1h 0m')
    fireEvent.click(screen.getByRole('button'))
    // The absent half must not acquire a marker, and the present half must.
    expect(screen.getByText('1,000 (unknown unit) \u2192 --')).toBeInTheDocument()
    expect(screen.getByText('--')).toBeInTheDocument() // the Distance tile
  })

  it('shows the empty state when there are no sessions (fails if the empty branch is dropped)', async () => {
    getSessions.mockResolvedValue(list({ sessions: [], total: 0 }))
    render(<LiveLinkSessionsTab vin="V1" />)
    expect(await screen.findByText('livelink.sessions.noRecords')).toBeInTheDocument()
  })
})
