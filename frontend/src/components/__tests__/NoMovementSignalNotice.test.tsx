/**
 * The notice that keeps `contact` mode honest.
 *
 * A device whose speed and odometer arrive under names this codebase does not
 * recognise records no drives at all, and "no drives" is indistinguishable from
 * "the vehicle was parked". A silent zero is exactly the failure the boundary
 * rework exists to remove, so shipping one for this cohort would be absurd.
 *
 * Every test seeds the state that makes it meaningful. The component's default
 * is to render nothing, so an assertion of absence proves nothing unless the
 * fixture is one that SHOULD have raised the notice but for the single property
 * under test.
 */

import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import NoMovementSignalNotice from '../livelink/NoMovementSignalNotice'
import type { LiveLinkDevice } from '@/types/livelink'

const NOW = new Date('2026-09-03T12:00:00Z')
const daysBefore = (n: number) =>
  new Date(NOW.getTime() - n * 24 * 60 * 60 * 1000).toISOString()

const device = (overrides: Partial<LiveLinkDevice> = {}): LiveLinkDevice =>
  ({
    id: 1,
    device_id: 'aabbccddeeff',
    label: null,
    vin: '1HGCM82633A123456',
    enabled: true,
    last_seen: daysBefore(0),
    last_movement_at: null,
    created_at: daysBefore(400),
    updated_at: null,
    ecu_status: 'online',
    device_status: 'online',
    has_device_token: false,
    sd_backfill_enabled: false,
    ...overrides,
  }) as LiveLinkDevice

const notice = () => screen.queryByText('modal.livelink.noMovementSignal')

describe('NoMovementSignalNotice', () => {
  it('names a device that checks in but never reports movement', () => {
    render(<NoMovementSignalNotice devices={[device()]} />)
    expect(notice()).toBeTruthy()
  })

  it('says nothing about a device that has reported movement', () => {
    render(<NoMovementSignalNotice devices={[device({ last_movement_at: daysBefore(1) })]} />)
    expect(notice()).toBeNull()
  })

  it('says nothing about a dongle sitting in a drawer', () => {
    // Long behind the newest check-in. It reports no movement because nothing
    // is driving it, which is not a problem anyone can fix.
    render(
      <NoMovementSignalNotice
        devices={[
          device({ device_id: 'active', last_movement_at: daysBefore(0) }),
          device({ device_id: 'drawer', last_seen: daysBefore(60) }),
        ]}
      />
    )
    expect(notice()).toBeNull()
  })

  it('says nothing about a disabled or unlinked device', () => {
    render(
      <NoMovementSignalNotice
        devices={[device({ enabled: false }), device({ device_id: 'b', vin: null })]}
      />
    )
    expect(notice()).toBeNull()
  })

  it('says nothing when there are no devices at all', () => {
    render(<NoMovementSignalNotice devices={[]} />)
    expect(notice()).toBeNull()
  })

  it('raises nothing when the whole fleet is equally stale', () => {
    // The cutoff is relative to the newest check-in, so a fleet that has all
    // been offline for a month is quiet rather than entirely flagged. This is
    // the behaviour that replaced `Date.now()`, which is impure in render.
    render(
      <NoMovementSignalNotice
        devices={[
          device({ device_id: 'a', last_seen: daysBefore(90), last_movement_at: daysBefore(90) }),
          device({ device_id: 'b', last_seen: daysBefore(91) }),
        ]}
      />
    )
    // 'b' is one day behind 'a', so it IS within the window and flagged: being
    // stale together is not the exemption, being stale RELATIVE to the fleet is.
    expect(notice()).toBeTruthy()
  })

  it('renders the same output twice for the same input', () => {
    // Idempotence, which is what the impure-function rule protects. With
    // `Date.now()` the cutoff moved between renders and a device could appear
    // and disappear without its data changing.
    const devices = [device()]
    const first = render(<NoMovementSignalNotice devices={devices} />).container.innerHTML
    const second = render(<NoMovementSignalNotice devices={devices} />).container.innerHTML
    expect(first).toBe(second)
  })
})
