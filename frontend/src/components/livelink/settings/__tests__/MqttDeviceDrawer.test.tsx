/**
 * The MQTT device drawer, including spec deletion-gate assertion 2: a device
 * with no vehicle can be linked from its own tab. Before this drawer the only
 * place to do that was the old modal's device table.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '../../../../__tests__/test-utils'
import type { IntegrationTab } from '@/types/livelink'

const svc = vi.hoisted(() => ({
  getDevices: vi.fn(),
  getDeviceReadings: vi.fn(),
  updateDevice: vi.fn(),
  deleteDevice: vi.fn(),
  updateParameter: vi.fn(),
  listTopicMaps: vi.fn(),
  createTopicMap: vi.fn(),
  deleteTopicMap: vi.fn(),
  getIntegrations: vi.fn(),
}))
vi.mock('@/services/livelinkService', () => ({ livelinkService: svc }))
const VEHICLE = { vin: '4EZFD3821P6080615', nickname: 'Durango', year: 2023, make: 'KZ', model: 'Durango' }
vi.mock('@/services/vehicleService', () => ({
  vehicleService: { list: () => Promise.resolve({ vehicles: [VEHICLE], total: 1 }) },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
// The reading list converts values through the user's unit preference, which
// reads the signed-in user. Units are DeviceReadingsList.test's concern.
vi.mock('@/hooks/useUnitPreference', async () => {
  const { presetUnitsFor } = await import('@/types/units')
  const units = presetUnitsFor('metric', 'us')
  return {
    useUnitPreference: () => ({ system: 'metric', showBoth: false, units, gallonStandard: 'us' }),
  }
})

import MqttDeviceDrawer from '../MqttDeviceDrawer'
import { answerConfirm, escapeConfirm } from '../../../../__tests__/confirmHelpers'

const TAB = {
  id: 'device:rvgateway',
  label: 'Mopeka',
  kind: 'generic_mqtt',
  status: 'attention',
  reason: 'not_linked',
  description: 'Two Mopeka Pro Check propane sensors.',
} as unknown as IntegrationTab

const device = (overrides: object = {}) => ({
  device_id: 'rvgateway',
  kind: 'generic_mqtt',
  label: 'Mopeka propane (2 tanks)',
  vin: null,
  preset_key: 'mopeka_two_tank',
  enabled: true,
  device_status: 'unknown',
  ecu_status: 'unknown',
  ...overrides,
})

const READING = {
  param_key: 'PROPANE_T1_LEVEL_PCT',
  display_name: 'Tank 1 level',
  unit: '%',
  value: 71,
  timestamp: '2026-09-22T12:00:00Z',
  show_on_dashboard: true,
}

const openDrawer = (tab = TAB) => {
  const onChanged = vi.fn()
  const onClose = vi.fn()
  const utils = render(<MqttDeviceDrawer open tab={tab} onClose={onClose} onChanged={onChanged} />)
  return { ...utils, onChanged, onClose }
}

beforeEach(() => {
  vi.clearAllMocks()
  svc.getDevices.mockResolvedValue({ total: 1, online_count: 0, devices: [device()] })
  svc.getDeviceReadings.mockResolvedValue({ device_id: 'rvgateway', vin: null, readings: [READING] })
  svc.updateDevice.mockResolvedValue({})
  svc.deleteDevice.mockResolvedValue(undefined)
  svc.updateParameter.mockResolvedValue({})
  svc.listTopicMaps.mockResolvedValue([])
  svc.getIntegrations.mockResolvedValue({ tabs: [TAB] })
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('MqttDeviceDrawer', () => {
  it('lets an unlinked device be linked from its own tab, and says what unlinked costs', async () => {
    const { onChanged } = openDrawer()

    expect(await screen.findByText('integrations.deviceNotLinked')).toBeInTheDocument()
    await screen.findByRole('option', { name: 'Durango' })
    fireEvent.change(screen.getByLabelText('integrations.sourceVehicle'), {
      target: { value: VEHICLE.vin },
    })

    await waitFor(() => expect(svc.updateDevice).toHaveBeenCalledWith('rvgateway', { vin: VEHICLE.vin }))
    await waitFor(() => expect(onChanged).toHaveBeenCalled())
  })

  it('unlinks with an empty VIN', async () => {
    svc.getDevices.mockResolvedValue({ total: 1, online_count: 0, devices: [device({ vin: VEHICLE.vin })] })
    openDrawer()
    await screen.findByRole('option', { name: 'Durango' })

    fireEvent.change(screen.getByLabelText('integrations.sourceVehicle'), { target: { value: '' } })

    await waitFor(() => expect(svc.updateDevice).toHaveBeenCalledWith('rvgateway', { vin: '' }))
  })

  it('deletes after confirmation, refreshes the card, and closes', async () => {
    const { onChanged, onClose } = openDrawer()

    fireEvent.click(await screen.findByRole('button', { name: 'integrations.deleteSource' }))
    await answerConfirm('confirm', 'forms:modal.livelink.confirmDeleteDevice')

    await waitFor(() => expect(svc.deleteDevice).toHaveBeenCalledWith('rvgateway'))
    expect(onChanged).toHaveBeenCalled()
    expect(onClose).toHaveBeenCalled()
  })

  // Regression pin: Escape on the delete confirm must not close the drawer.
  it('Escape closes the delete confirm and leaves the drawer open', async () => {
    const { onClose } = openDrawer()

    fireEvent.click(await screen.findByRole('button', { name: 'integrations.deleteSource' }))
    await escapeConfirm('forms:modal.livelink.confirmDeleteDevice')

    expect(onClose).not.toHaveBeenCalled()
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(svc.deleteDevice).not.toHaveBeenCalled()
  })

  it("opens a handmade device's mappings and keeps a preset device's closed", async () => {
    const { unmount } = openDrawer()
    const preset = await screen.findByText('integrations.advancedMappings')
    expect(preset.closest('details')).not.toHaveAttribute('open')
    unmount()

    svc.getDevices.mockResolvedValue({
      total: 1,
      online_count: 0,
      devices: [device({ preset_key: null, label: 'Shed sensors' })],
    })
    openDrawer({ ...TAB, label: 'Shed sensors', description: null } as unknown as IntegrationTab)
    const handmade = await screen.findByText('integrations.advancedMappings')
    expect(handmade.closest('details')).toHaveAttribute('open')
  })

  it('keeps the header usable when the readings cannot load', async () => {
    // Linking is often exactly what fixes it.
    svc.getDeviceReadings.mockRejectedValue(new Error('500'))
    openDrawer()

    expect(await screen.findByText('integrations.readingsLoadError')).toBeInTheDocument()
    expect(screen.getByLabelText('integrations.sourceVehicle')).toBeEnabled()
  })

  it('follows the server on reopen, not a lingering local switch', async () => {
    const { rerender } = openDrawer()
    const toggle = await screen.findByRole('checkbox', { name: 'Tank 1 level' })
    fireEvent.click(toggle)
    await waitFor(() => expect(svc.updateParameter).toHaveBeenCalled())

    // The server says it is shown again, the OPPOSITE of the click.
    svc.getDeviceReadings.mockResolvedValue({
      device_id: 'rvgateway',
      vin: null,
      readings: [{ ...READING, show_on_dashboard: true }],
    })
    const callsBefore = svc.getDeviceReadings.mock.calls.length
    rerender(<MqttDeviceDrawer open={false} tab={TAB} onClose={vi.fn()} onChanged={vi.fn()} />)
    rerender(<MqttDeviceDrawer open tab={TAB} onClose={vi.fn()} onChanged={vi.fn()} />)

    await waitFor(() => expect(svc.getDeviceReadings.mock.calls.length).toBeGreaterThan(callsBefore))
    expect(await screen.findByRole('checkbox', { name: 'Tank 1 level' })).toBeChecked()
  })

  it('renames the device on Save and retitles a handmade drawer', async () => {
    svc.getDevices.mockResolvedValue({
      total: 1,
      online_count: 0,
      devices: [device({ preset_key: null, label: 'Shed sensors' })],
    })
    const { onChanged } = openDrawer({ ...TAB, label: 'Shed sensors' } as unknown as IntegrationTab)
    const field = await screen.findByLabelText('integrations.deviceLabel')

    fireEvent.change(field, { target: { value: 'Barn sensors' } })
    svc.getDevices.mockResolvedValue({
      total: 1,
      online_count: 0,
      devices: [device({ preset_key: null, label: 'Barn sensors' })],
    })
    fireEvent.click(screen.getByRole('button', { name: 'forms:modal.livelink.save' }))

    await waitFor(() => expect(svc.updateDevice).toHaveBeenCalledWith('rvgateway', { label: 'Barn sensors' }))
    expect(await screen.findByRole('dialog', { name: 'Barn sensors' })).toBeInTheDocument()
    expect(onChanged).toHaveBeenCalled()
  })

  it('states the status the device has now, not the one it had when opened', async () => {
    // The drawer opened on a tab object captured at click time. Unlinking
    // made it "Not linked", and the drawer went on saying "Receiving data".
    const receiving = { ...TAB, status: 'ok', reason: 'receiving' } as unknown as IntegrationTab
    svc.getDevices.mockResolvedValue({ total: 1, online_count: 0, devices: [device({ vin: VEHICLE.vin })] })
    openDrawer(receiving)
    expect(await screen.findByText('integrations.statusReceiving')).toBeInTheDocument()
    await screen.findByRole('option', { name: 'Durango' })

    svc.getDevices.mockResolvedValue({ total: 1, online_count: 0, devices: [device({ vin: null })] })
    svc.getIntegrations.mockResolvedValue({ tabs: [{ ...TAB, status: 'attention', reason: 'not_linked' }] })
    fireEvent.change(screen.getByLabelText('integrations.sourceVehicle'), { target: { value: '' } })

    expect(await screen.findByText('integrations.statusNotLinked')).toBeInTheDocument()
    expect(screen.queryByText('integrations.statusReceiving')).not.toBeInTheDocument()
  })
})
