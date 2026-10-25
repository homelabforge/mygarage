/**
 * WiCAN's drawer, with the REAL DeviceTable and DeviceRow: a mocked table
 * would pass with stale firmware props, which is the bug the reload-both rule
 * exists for.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import type { IntegrationTab } from '@/types/livelink'

const svc = vi.hoisted(() => ({
  getSettings: vi.fn(),
  getDevices: vi.fn(),
  getFirmwareLatest: vi.fn(),
  getDeviceFirmwareStatus: vi.fn(),
  getMQTTSettings: vi.fn(),
  getMQTTStatus: vi.fn(),
  updateMQTTSettings: vi.fn(),
  restartMQTTSubscriber: vi.fn(),
  regenerateGlobalToken: vi.fn(),
  checkFirmwareUpdates: vi.fn(),
  updateSettings: vi.fn(),
  // Called by the real DeviceTable and DeviceRow on mount or on click.
  listSources: vi.fn(),
  skipFirmwareVersion: vi.fn(),
  unskipFirmwareVersion: vi.fn(),
  getDeviceParamKeys: vi.fn(),
}))
vi.mock('@/services/livelinkService', () => ({ livelinkService: svc }))
vi.mock('@/services/vehicleService', () => ({
  vehicleService: { list: () => Promise.resolve({ vehicles: [], total: 0 }) },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() } }))

import WicanSettingsDrawer from '../WicanSettingsDrawer'

const TAB = { id: 'wican', label: 'WiCAN', kind: 'wican' } as unknown as IntegrationTab

const device = (id: string, kind: string) => ({
  device_id: id,
  kind,
  label: id,
  vin: null,
  enabled: true,
  device_status: 'offline',
  ecu_status: 'unknown',
  fw_version: '4.50',
  sta_ip: null,
  has_device_token: false,
})

const FW = (skipped: string | null) => [
  {
    device_id: 'wican1',
    current_version: '4.50',
    latest_version: '4.51',
    update_available: true,
    release_url: null,
    firmware_track: 'pro',
    skipped_version: skipped,
  },
]

const renderDrawer = () => {
  const onChanged = vi.fn()
  render(<WicanSettingsDrawer open tab={TAB} onClose={vi.fn()} onChanged={onChanged} />)
  return { onChanged }
}

beforeEach(() => {
  vi.clearAllMocks()
  svc.getSettings.mockResolvedValue({
    enabled: true,
    has_global_token: true,
    ingestion_url: 'http://garage/api/v1/livelink/ingest',
    firmware_check_enabled: true,
  })
  svc.getDevices.mockResolvedValue({
    total: 3,
    online_count: 0,
    devices: [device('wican1', 'wican'), device('tq_1', 'torque'), device('rvgw', 'generic_mqtt')],
  })
  svc.getFirmwareLatest.mockResolvedValue({ latest_tag: 'v4.51p', release_url: null })
  svc.getDeviceFirmwareStatus.mockResolvedValue(FW(null))
  svc.getMQTTSettings.mockResolvedValue({ topic_prefix: 'wican' })
  svc.getMQTTStatus.mockResolvedValue({ running: true, connection_status: 'connected' })
  svc.updateMQTTSettings.mockImplementation((u: object) => Promise.resolve({ topic_prefix: 'wican', ...u }))
  svc.restartMQTTSubscriber.mockResolvedValue({ running: true, connection_status: 'connecting' })
  svc.listSources.mockResolvedValue([
    { kind: 'wican', capabilities: ['commands', 'odometer', 'sd_backfill', 'telemetry'], syncs_odometer: true },
  ])
  svc.skipFirmwareVersion.mockResolvedValue({})
  svc.getDeviceParamKeys.mockResolvedValue([])
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('WicanSettingsDrawer', () => {
  it('lists only WiCAN devices', async () => {
    renderDrawer()

    expect(await screen.findByText('wican1', { selector: 'button' })).toBeInTheDocument()
    expect(screen.queryByText('tq_1')).not.toBeInTheDocument()
    expect(screen.queryByText('rvgw')).not.toBeInTheDocument()
  })

  it('saving the topic prefix leaves the restart to the server', async () => {
    // The settings PUT restarts a running subscriber itself when the prefix
    // changes. A second restart from here would just bounce the connection.
    const { onChanged } = renderDrawer()
    const field = await screen.findByLabelText('settings:integrations.wicanTopicPrefix')

    fireEvent.change(field, { target: { value: 'garage' } })
    fireEvent.click(screen.getAllByRole('button', { name: 'modal.livelink.save' })[0])

    await waitFor(() => expect(svc.updateMQTTSettings).toHaveBeenCalledWith({ topic_prefix: 'garage' }))
    await waitFor(() => expect(onChanged).toHaveBeenCalled())
    expect(svc.restartMQTTSubscriber).not.toHaveBeenCalled()
  })

  it('does not start a stopped subscriber just to save the prefix', async () => {
    svc.getMQTTStatus.mockResolvedValue({ running: false, connection_status: 'disabled' })
    renderDrawer()
    const field = await screen.findByLabelText('settings:integrations.wicanTopicPrefix')

    fireEvent.change(field, { target: { value: 'garage' } })
    fireEvent.click(screen.getAllByRole('button', { name: 'modal.livelink.save' })[0])

    await waitFor(() => expect(svc.updateMQTTSettings).toHaveBeenCalled())
    expect(svc.restartMQTTSubscriber).not.toHaveBeenCalled()
  })

  it('reveals a regenerated token once', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    svc.regenerateGlobalToken.mockResolvedValue({ token: 'tok-123' })
    renderDrawer()

    fireEvent.click(await screen.findByRole('button', { name: 'modal.livelink.regenerate' }))

    expect(await screen.findByDisplayValue('tok-123')).toBeInTheDocument()
  })

  it('reads device firmware only after the check has finished', async () => {
    // The status read compares against the latest release the check refreshes.
    let finish: (v: unknown) => void = () => {}
    svc.checkFirmwareUpdates.mockReturnValue(new Promise((resolve) => (finish = resolve)))
    renderDrawer()

    fireEvent.click(await screen.findByRole('button', { name: 'modal.livelink.checkNow' }))
    await waitFor(() => expect(svc.checkFirmwareUpdates).toHaveBeenCalled())
    const readsBefore = svc.getDeviceFirmwareStatus.mock.calls.length

    await new Promise((r) => setTimeout(r, 20))
    expect(svc.getDeviceFirmwareStatus).toHaveBeenCalledTimes(readsBefore)

    finish({ latest_tag: 'v4.52p', release_url: null })
    await waitFor(() => expect(svc.getDeviceFirmwareStatus).toHaveBeenCalledTimes(readsBefore + 1))
  })

  it('shows a skipped version as skipped once the skip lands', async () => {
    const { onChanged } = renderDrawer()
    expect(await screen.findByText('modal.livelink.updateBadge')).toBeInTheDocument()

    svc.getDeviceFirmwareStatus.mockResolvedValue(FW('4.51'))
    fireEvent.click(screen.getByTitle('modal.livelink.skipVersion'))

    expect(await screen.findByText('modal.livelink.skippedBadge')).toBeInTheDocument()
    expect(screen.queryByText('modal.livelink.updateBadge')).not.toBeInTheDocument()
    expect(onChanged).toHaveBeenCalled()
  })
})
