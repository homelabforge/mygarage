/**
 * The router from a settings target to its drawer.
 *
 * Each drawer is stubbed to render its name ONLY when open, as a real closed
 * Drawer renders nothing. A stub that always rendered would let a router that
 * opens every drawer pass.
 *
 * This is what licensed deleting LiveLinkSettingsModal: every kind of tab,
 * including one for a source module nobody has written a drawer for, opens a
 * drawer of its own, so no tab can reach the modal's old fallback.
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import type { IntegrationTab } from '@/types/livelink'

vi.mock('../GeneralSettingsDrawer', () => ({
  default: ({ open }: { open: boolean }) => (open ? <p>general-drawer</p> : null),
}))
vi.mock('../MosquittoSettingsDrawer', () => ({
  default: ({ open }: { open: boolean }) => (open ? <p>mosquitto-drawer</p> : null),
}))
vi.mock('../WicanSettingsDrawer', () => ({
  default: ({ open }: { open: boolean }) => (open ? <p>wican-drawer</p> : null),
}))
vi.mock('../TorqueSettingsDrawer', () => ({
  default: ({ open }: { open: boolean }) => (open ? <p>torque-drawer</p> : null),
}))
vi.mock('../SourceDevicesDrawer', () => ({
  default: ({ open }: { open: boolean }) => (open ? <p>devices-drawer</p> : null),
}))
vi.mock('../MqttDeviceDrawer', () => ({
  default: ({ open }: { open: boolean }) => (open ? <p>mqtt-drawer</p> : null),
}))
vi.mock('../PresetDrawer', () => ({
  PRESET_TAB_PREFIX: 'preset:',
  default: ({ open }: { open: boolean }) => (open ? <p>preset-drawer</p> : null),
}))

const DRAWERS = [
  'general-drawer',
  'mosquitto-drawer',
  'wican-drawer',
  'torque-drawer',
  'devices-drawer',
  'mqtt-drawer',
  'preset-drawer',
]

/** Exactly `expected` renders, and no other drawer. */
const expectOnly = (expected: string | null): void => {
  for (const name of DRAWERS) {
    if (name === expected) expect(screen.getByText(name)).toBeInTheDocument()
    else expect(screen.queryByText(name), name).not.toBeInTheDocument()
  }
}

import LiveLinkSettingsDrawers from '../LiveLinkSettingsDrawers'
import { withConfirm } from '../../../../__tests__/confirmHelpers'

const tab = (id: string, kind: string | null): IntegrationTab =>
  ({
    id,
    label: id,
    kind,
    status: 'ok',
    reason: 'receiving',
    description: null,
    device_count: 0,
    online_count: 0,
    linked_count: 0,
    firmware_updates: 0,
  }) as IntegrationTab

describe('LiveLinkSettingsDrawers', () => {
  it('opens the general drawer for the gear, and only it', () => {
    render(<LiveLinkSettingsDrawers target={{ type: 'general' }} onClose={vi.fn()} onChanged={vi.fn()} />, { wrapper: withConfirm })
    expectOnly('general-drawer')
  })

  it('opens nothing when there is no target', () => {
    render(<LiveLinkSettingsDrawers target={null} onClose={vi.fn()} onChanged={vi.fn()} />, { wrapper: withConfirm })
    expectOnly(null)
  })

  it('opens the Mosquitto drawer for the broker tab, and only it', () => {
    const broker = tab('broker', null)
    render(<LiveLinkSettingsDrawers target={{ type: 'tab', tab: broker }} onClose={vi.fn()} onChanged={vi.fn()} />, { wrapper: withConfirm })
    expectOnly('mosquitto-drawer')
  })

  it('opens the WiCAN drawer for the WiCAN tab, and only it', () => {
    const wican = tab('wican', 'wican')
    render(<LiveLinkSettingsDrawers target={{ type: 'tab', tab: wican }} onClose={vi.fn()} onChanged={vi.fn()} />, { wrapper: withConfirm })
    expectOnly('wican-drawer')
  })

  it.each([
    ['torque', 'torque', 'torque-drawer'],
    // Every Mopeka sensor. Its kind is generic_mqtt too, so the id must win.
    ['preset:mopeka', 'generic_mqtt', 'preset-drawer'],
    // Any MQTT device mapped by hand.
    ['device:rvgw', 'generic_mqtt', 'mqtt-drawer'],
    // A kind nobody wrote a drawer for still gets its devices (spec G2).
    ['obdlink', 'obdlink', 'devices-drawer'],
  ])('opens the right drawer for the %s tab, and only it', (id, kind, drawer) => {
    const t = tab(id, kind)
    render(<LiveLinkSettingsDrawers target={{ type: 'tab', tab: t }} onClose={vi.fn()} onChanged={vi.fn()} />, { wrapper: withConfirm })
    expectOnly(drawer)
  })

})
