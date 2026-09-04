/**
 * The notice that keeps `contact` mode honest.
 *
 * Deciding WHICH devices cannot have their movement read needs their parameter
 * keys, so the backend decides and this renders the answer. What is left to
 * test here is that it renders that answer and never a guess of its own: the
 * previous version inferred the cohort from `last_movement_at == null`, which
 * migration 098 makes true for every device that exists.
 */

import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import NoMovementSignalNotice from '../livelink/NoMovementSignalNotice'
import type { LiveLinkDevice } from '@/types/livelink'

// The shared setup mocks `t` as `(key) => key`, which discards interpolation --
// and the device names ARE the interpolation here, so under that mock a notice
// naming the wrong vehicle is indistinguishable from one naming the right one.
// Overridden for this file only, so the names become assertable.
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, unknown>) =>
      options?.devices ? `${key}:${String(options.devices)}` : key,
    i18n: { language: 'en', changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children: React.ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: () => {} },
}))

const device = (overrides: Partial<LiveLinkDevice> = {}): LiveLinkDevice =>
  ({
    id: 1,
    device_id: 'aabbccddeeff',
    label: null,
    vin: '1HGCM82633A123456',
    enabled: true,
    last_seen: '2026-09-03T12:00:00Z',
    last_movement_at: null,
    movement_unreadable: false,
    created_at: '2025-08-01T12:00:00Z',
    updated_at: null,
    ecu_status: 'online',
    device_status: 'online',
    has_device_token: false,
    sd_backfill_enabled: false,
    ...overrides,
  }) as LiveLinkDevice

const notice = () => screen.queryByText('modal.livelink.noMovementSignal')

describe('NoMovementSignalNotice', () => {
  it('names a device the backend found unreadable', () => {
    render(<NoMovementSignalNotice devices={[device({ movement_unreadable: true })]} />)
    expect(notice()).toBeTruthy()
  })

  it('stays quiet for a device that has simply not moved yet', () => {
    // The day-one case, and the whole reason this component stopped deciding
    // for itself: no movement is on record, because the column that records it
    // was created by the migration that shipped it. The backend can see the
    // device is publishing only its parked heartbeat. This component cannot,
    // and must not guess.
    render(
      <NoMovementSignalNotice
        devices={[device({ last_movement_at: null, movement_unreadable: false })]}
      />
    )
    expect(notice()).toBeNull()
  })

  it('names only the unreadable device when the fleet is mixed', () => {
    render(
      <NoMovementSignalNotice
        devices={[
          device({ device_id: 'readable', label: 'Ram', movement_unreadable: false }),
          device({ device_id: 'unreadable', label: 'Mirage', movement_unreadable: true }),
        ]}
      />
    )
    expect(notice()).toBeTruthy()
    expect(screen.getByText(/Mirage/)).toBeTruthy()
    expect(screen.queryByText(/Ram/)).toBeNull()
  })

  it('falls back to the device id when a device has no label', () => {
    render(
      <NoMovementSignalNotice
        devices={[device({ device_id: 'aabbccddeeff', label: null, movement_unreadable: true })]}
      />
    )
    expect(screen.getByText(/aabbccddeeff/)).toBeTruthy()
  })

  it('says nothing when there are no devices at all', () => {
    render(<NoMovementSignalNotice devices={[]} />)
    expect(notice()).toBeNull()
  })

  it('renders the same output twice for the same input', () => {
    const devices = [device({ movement_unreadable: true })]
    const first = render(<NoMovementSignalNotice devices={devices} />).container.innerHTML
    const second = render(<NoMovementSignalNotice devices={devices} />).container.innerHTML
    expect(first).toBe(second)
  })
})
