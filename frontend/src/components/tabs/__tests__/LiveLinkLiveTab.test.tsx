import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, act, cleanup } from '../../../__tests__/test-utils'
import type { VehicleLiveLinkStatus } from '../../../types/livelink'
import { presetUnitsFor } from '../../../types/units'

// ─────────────────────────────────────────────────────────────────────────────
// Timer strategy (harness note — deviates from the brief's single fake-timer
// flush, and here is why):
//
// LiveLinkLiveTab fires an async `livelinkService.getVehicleStatus(vin)` in its
// mount effect. Under React 19 + Testing Library, committing the RESOLVED
// telemetry tree is deferred to React's scheduler, which needs one real
// event-loop tick. `vi.useFakeTimers()` freezes every timing primitive jsdom's
// scheduler can use (setTimeout / setImmediate / MessageChannel are all
// timer-backed), so `act()` never observes React going idle and hangs
// indefinitely — even a bare `await Promise.resolve()` inside `act()` deadlocks
// on the resolve path (the reject path's tiny tree commits synchronously, so it
// does not). Verified empirically.
//
// So we split by what each test needs:
//  • Poll tests (LD3) assert only the *call count* of `getVehicleStatus`. That
//    call is synchronous — it happens BEFORE the `await` inside `fetchStatus`,
//    and again synchronously each time the interval callback runs — so we never
//    need the resolved commit. Fake timers drive the 5s interval deterministically
//    and the advance is wrapped in a synchronous `act()` (never awaited), which
//    cannot hang.
//  • Content tests (SDQ-C) assert the committed DOM (status label + dot tone,
//    the warning marker, the error state). They never touch the interval, so
//    they run on REAL timers and settle the mount with `findBy*` — the interval
//    fires only every 5s of real time and each test finishes in milliseconds.
//
// The assertions, fixtures, and poll discrimination are exactly those the brief
// specifies; only the flush mechanism differs.
// ─────────────────────────────────────────────────────────────────────────────

const getVehicleStatus = vi.fn()
vi.mock('@/services/livelinkService', () => ({
  livelinkService: { getVehicleStatus: (vin: string) => getVehicleStatus(vin) },
}))
vi.mock('@/hooks/useUnitPreference', () => ({
  useUnitPreference: () => ({
    system: 'imperial',
    showBoth: false,
    units: presetUnitsFor('imperial', 'us'),
    gallonStandard: 'us',
  }),
}))
vi.mock('@/hooks/useTimeFormat', () => ({ useTimeFormat: () => ({ timeFormat: '12h' }) }))
// The gauge arithmetic is stubbed here so the poll/status assertions below stay
// about polling and status. `LiveLinkLiveTab.units.test.tsx` drives the REAL
// layer, which is where the rendered figures and the unknown-unit wording are
// pinned.
vi.mock('@/utils/telemetryUnits', () => ({
  convertTelemetryValue: (v: number) => ({ text: String(v), unit: 'rpm', unverified: false }),
  getParamDisplayName: (k: string, dn: string | null) => dn ?? k,
}))
vi.mock('@/utils/parseAPITimestamp', () => ({ formatTime: () => '12:00:00' }))

import LiveLinkLiveTab from '../LiveLinkLiveTab'

let visState: DocumentVisibilityState = 'visible'
// Contract-valid typed builder (M1): `satisfies VehicleLiveLinkStatus` fails at type-check if a
// required field drifts (`vin`/`device_status`/`ecu_status`) — no `as unknown as` schema suppression.
const okStatus = (overrides: Partial<VehicleLiveLinkStatus> = {}) =>
  ({
    vin: 'V1',
    device_id: 'DEV1',
    device_status: 'online',
    ecu_status: 'online',
    rssi: -55,
    current_session_id: 1,
    session_duration_seconds: 120,
    latest_values: [
      { param_key: 'rpm', value: 3200, unit: 'rpm', display_name: 'Engine RPM', in_warning: false, timestamp: 'x' },
    ],
    ...overrides,
  }) satisfies VehicleLiveLinkStatus

beforeEach(() => {
  vi.clearAllMocks()
  visState = 'visible'
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => visState })
})
afterEach(() => {
  // m1: UNMOUNT first (so no interval callback fires during teardown), THEN discard pending
  // timers with clearAllTimers (never runOnlyPendingTimers — that would run a queued async poll),
  // and only then restore real timers.
  cleanup()
  vi.clearAllTimers()
  vi.useRealTimers()
})

describe('LiveLinkLiveTab — polling loop (LD3)', () => {
  it('fetches on mount and polls again every 5s while visible (fails if the 5s setInterval poll is removed or its period changes)', () => {
    vi.useFakeTimers()
    getVehicleStatus.mockResolvedValue(okStatus())
    render(<LiveLinkLiveTab vin="V1" />)
    // The mount effect calls getVehicleStatus synchronously (before its own await).
    expect(getVehicleStatus).toHaveBeenCalledTimes(1)
    expect(getVehicleStatus.mock.calls).toStrictEqual([['V1']]) // M1: exact call identity — the sole arg is the VIN
    act(() => { vi.advanceTimersByTime(5000) })
    expect(getVehicleStatus).toHaveBeenCalledTimes(2)
    act(() => { vi.advanceTimersByTime(5000) })
    expect(getVehicleStatus).toHaveBeenCalledTimes(3)
  })

  it('pauses polling while hidden and resumes (with an immediate fetch) on visible (fails if the visibilitychange pause/resume wiring is disturbed)', () => {
    vi.useFakeTimers()
    getVehicleStatus.mockResolvedValue(okStatus())
    render(<LiveLinkLiveTab vin="V1" />)
    expect(getVehicleStatus).toHaveBeenCalledTimes(1)
    visState = 'hidden'
    act(() => { document.dispatchEvent(new Event('visibilitychange')) })
    act(() => { vi.advanceTimersByTime(15000) })
    expect(getVehicleStatus).toHaveBeenCalledTimes(1) // no polls fire while hidden
    visState = 'visible'
    act(() => { document.dispatchEvent(new Event('visibilitychange')) })
    expect(getVehicleStatus).toHaveBeenCalledTimes(2) // immediate fetch on resume
    act(() => { vi.advanceTimersByTime(5000) })
    expect(getVehicleStatus).toHaveBeenCalledTimes(3) // interval restarted
  })
})

describe('LiveLinkLiveTab — status mapping + gauge warning (SDQ-C)', () => {
  it('maps device/ecu status to the right connection label AND status-dot tone (fails if the running/parked/offline mapping is wrong OR getStatusColor collapses to one tone)', async () => {
    // M2: assert the status DOT class per state — not just getStatusText. getStatusColor could return
    // 'success' for every state and the text-only assertion would still pass. The dot's className STRING
    // encodes the runtime-selected token (jsdom exposes className directly; this is a structural token
    // assertion, NOT a computed-colour toHaveClass-on-CSS check). online+ecu online → success;
    // online+ecu offline → info; device offline → danger.
    getVehicleStatus.mockResolvedValue(okStatus({ device_status: 'online', ecu_status: 'online' }))
    const online = render(<LiveLinkLiveTab vin="V1" />)
    expect(await screen.findByText('livelink.vehicleRunning')).toBeInTheDocument()
    expect(online.container.querySelector('.rounded-full')).toHaveClass('bg-success')
    online.unmount()

    getVehicleStatus.mockResolvedValue(okStatus({ device_status: 'online', ecu_status: 'offline' }))
    const parked = render(<LiveLinkLiveTab vin="V1" />)
    expect(await screen.findByText('livelink.vehicleParked')).toBeInTheDocument()
    expect(parked.container.querySelector('.rounded-full')).toHaveClass('bg-info')
    parked.unmount()

    getVehicleStatus.mockResolvedValue(okStatus({ device_status: 'offline', ecu_status: 'offline' }))
    const offline = render(<LiveLinkLiveTab vin="V1" />)
    expect(await screen.findByText('livelink.wicanOffline')).toBeInTheDocument()
    expect(offline.container.querySelector('.rounded-full')).toHaveClass('bg-danger')
  })

  it('renders the AlertTriangle marker only for an in_warning gauge (fails if the warning marker is dropped or shown unconditionally)', async () => {
    getVehicleStatus.mockResolvedValue(
      okStatus({
        latest_values: [
          { param_key: 'rpm', value: 3200, unit: 'rpm', display_name: 'Engine RPM', in_warning: false, timestamp: 'x' },
          { param_key: 'coolant', value: 130, unit: 'C', display_name: 'Coolant Temp', in_warning: true, timestamp: 'x' },
        ],
      }),
    )
    const { container } = render(<LiveLinkLiveTab vin="V1" />)
    expect(await screen.findByText('Engine RPM')).toBeInTheDocument()
    expect(screen.getByText('Coolant Temp')).toBeInTheDocument()
    // The warning marker (lucide AlertTriangle → svg.lucide-triangle-alert) renders for exactly the one
    // in_warning gauge — a structural conditional, not a colour assertion.
    expect(container.querySelectorAll('svg.lucide-triangle-alert')).toHaveLength(1)
  })

  it('shows the error EmptyState when the fetch fails (fails if the error branch is dropped)', async () => {
    getVehicleStatus.mockRejectedValue(new Error('boom'))
    render(<LiveLinkLiveTab vin="V1" />)
    expect(await screen.findByText('livelink.fetchStatusError')).toBeInTheDocument()
    expect(screen.getByText('livelink.ensureDeviceLinked')).toBeInTheDocument()
  })
})
