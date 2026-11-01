/**
 * The LiveLink settings drawers, read by name (B6-3). Every row's buttons say
 * which row they act on, nothing icon-only goes nameless, and the device token
 * shows in a real dialog. Strings come from the en bundle so two rows' names
 * actually differ here, where the global key-only mock would make them equal.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import type { IntegrationTab, LiveLinkDevice } from '@/types/livelink'

vi.mock('react-i18next', async () => (await import('@/__tests__/i18nEn')).reactI18nextEn())

const svc = vi.hoisted(() => ({
  listSources: vi.fn(),
  getDeviceParamKeys: vi.fn(),
  generateDeviceToken: vi.fn(),
  updateDevice: vi.fn(),
  listTopicMaps: vi.fn(),
  deleteTopicMap: vi.fn(),
  getDeviceReadings: vi.fn(),
  getDevices: vi.fn(),
  createTorqueSource: vi.fn(),
  getSettings: vi.fn(),
  getFirmwareLatest: vi.fn(),
  getDeviceFirmwareStatus: vi.fn(),
  getMQTTSettings: vi.fn(),
  getMQTTStatus: vi.fn(),
  regenerateGlobalToken: vi.fn(),
}))
vi.mock('@/services/livelinkService', () => ({ livelinkService: svc }))
const VEHICLE = { vin: 'ML32A5HJ9KH009478', nickname: 'Mirage', year: 2019, make: 'Mitsubishi', model: 'Mirage' }
vi.mock('@/services/vehicleService', () => ({
  vehicleService: { list: () => Promise.resolve({ vehicles: [VEHICLE], total: 1 }) },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() } }))

import DeviceTable from '../DeviceTable'
import SensorBlock from '../SensorBlock'
import TopicMapEditor from '../TopicMapEditor'
import TorqueSettingsDrawer from '../TorqueSettingsDrawer'
import WicanSettingsDrawer from '../WicanSettingsDrawer'

const WICAN_CAPS = { kind: 'wican', capabilities: ['commands', 'odometer', 'sd_backfill', 'telemetry'], syncs_odometer: true }
const TORQUE_CAPS = { kind: 'torque', capabilities: ['odometer', 'telemetry'], syncs_odometer: false }

const wican = (id: string, label: string, overrides: Partial<LiveLinkDevice> = {}): LiveLinkDevice =>
  ({
    device_id: id,
    kind: 'wican',
    label,
    vin: null,
    enabled: true,
    online: true,
    device_status: 'online',
    ecu_status: 'unknown',
    fw_version: '4.50',
    sta_ip: '192.168.1.40',
    has_device_token: false,
    ...overrides,
  }) as unknown as LiveLinkDevice

const firmware = (deviceId: string, skipped: string | null) => ({
  device_id: deviceId,
  current_version: '4.50',
  latest_version: '4.51',
  update_available: true,
  release_url: null,
  firmware_track: 'pro',
  skipped_version: skipped,
})

beforeEach(() => {
  vi.clearAllMocks()
  svc.listSources.mockResolvedValue([WICAN_CAPS, TORQUE_CAPS])
  svc.getDeviceParamKeys.mockResolvedValue(['TORQUE_ODOMETER'])
  svc.generateDeviceToken.mockResolvedValue({ token: 'dev-tok-1' })
  svc.updateDevice.mockResolvedValue({})
  svc.getDeviceReadings.mockResolvedValue({ online: true, readings: [] })
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('DeviceRow names', () => {
  const renderTable = (): void => {
    render(
      <DeviceTable
        devices={[wican('d1', 'Garage dongle'), wican('d2', 'RV dongle', { has_device_token: true, sta_ip: null })]}
        vehicles={[VEHICLE as never]}
        deviceFirmware={[firmware('d1', null), firmware('d2', '4.51')]}
        mqttConnected
        onChanged={vi.fn()}
      />,
    )
  }

  it('names every row action after its device', async () => {
    renderTable()
    // The capability-gated controls arrive with the source catalogue.
    expect(await screen.findByRole('button', { name: 'Check battery voltage: Garage dongle' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Check battery voltage: RV dongle' })).toBeInTheDocument()

    expect(screen.getByRole('button', { name: 'Delete device: Garage dongle' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Delete device: RV dongle' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Device settings: Garage dongle' })).toHaveAttribute(
      'aria-expanded',
      'false',
    )
    expect(screen.getByRole('button', { name: 'Device settings: RV dongle' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Generate device token: Garage dongle' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Revoke device token: RV dongle' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Skip this version: Garage dongle' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Resume update notifications: RV dongle' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open device UI: Garage dongle' })).toHaveAttribute(
      'href',
      'http://192.168.1.40',
    )
    expect(screen.getByRole('combobox', { name: 'Vehicle: Garage dongle' })).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'Vehicle: RV dongle' })).toBeInTheDocument()
  })

  it('names the label editor and its save button', async () => {
    renderTable()
    fireEvent.click(await screen.findByRole('button', { name: 'Garage dongle' }))

    fireEvent.change(screen.getByRole('textbox', { name: 'Label' }), { target: { value: 'Shop dongle' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(svc.updateDevice).toHaveBeenCalledWith('d1', { label: 'Shop dongle' }))
  })

  it('ties the device settings labels to their fields', async () => {
    renderTable()
    const toggle = await screen.findByRole('button', { name: 'Device settings: Garage dongle' })
    fireEvent.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')

    expect(screen.getByRole('textbox', { name: 'Device address (IP or hostname)' })).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'Odometer units' })).toHaveValue('auto')
  })

  it('ties the odometer parameter label to its select', async () => {
    const phone = {
      ...wican('tq_1', 'Pixel'),
      kind: 'torque',
      odometer_param_key: null,
    } as unknown as LiveLinkDevice
    render(<DeviceTable devices={[phone]} vehicles={[]} onChanged={vi.fn()} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Device settings: Pixel' }))

    const param = screen.getByRole('combobox', { name: 'Odometer parameter' })
    await within(param).findByRole('option', { name: 'TORQUE_ODOMETER' })
    expect(param).toHaveValue('')
  })
})

describe('DeviceTable token dialog', () => {
  const generate = async (): Promise<HTMLElement> => {
    render(<DeviceTable devices={[wican('d1', 'Garage dongle')]} vehicles={[]} onChanged={vi.fn()} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Generate device token: Garage dongle' }))
    return screen.findByRole('dialog', { name: 'Device Token Generated' })
  }

  it('is a named dialog with the token, a named copy button and focus inside', async () => {
    const dialog = await generate()
    const token = within(dialog).getByRole('textbox', { name: 'Token for device d1' })
    expect(token).toHaveValue('dev-tok-1')
    expect(within(dialog).getByRole('button', { name: 'Copy Token for device d1' })).toBeInTheDocument()
    await waitFor(() => expect(dialog).toContainElement(document.activeElement as HTMLElement))
  })

  it('closes on Escape', async () => {
    await generate()
    fireEvent.keyDown(document, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Device Token Generated' })).toBeNull())
  })

  it('closes on Done', async () => {
    const dialog = await generate()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Done' }))
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Device Token Generated' })).toBeNull())
  })
})

describe('TopicMapEditor names', () => {
  it('names each remove button after its mapping', async () => {
    svc.listTopicMaps.mockResolvedValue([
      { id: 1, device_id: 'rvgw', topic: 'rv/tank1/level', param_key: 'TANK1_LEVEL', unit: '%' },
      { id: 2, device_id: 'rvgw', topic: 'rv/tank2/level', param_key: 'TANK2_LEVEL', unit: '%' },
    ])
    svc.deleteTopicMap.mockResolvedValue(undefined)
    render(<TopicMapEditor deviceId="rvgw" onMappingsChanged={vi.fn()} />)

    expect(
      await screen.findByRole('button', { name: 'Remove mapping: rv/tank1/level to TANK1_LEVEL' }),
    ).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Remove mapping: rv/tank2/level to TANK2_LEVEL' }))
    await waitFor(() => expect(svc.deleteTopicMap).toHaveBeenCalledWith(2))
  })
})

describe('SensorBlock names', () => {
  it('says whose mappings the toggle shows, and whether they are shown', async () => {
    svc.listTopicMaps.mockResolvedValue([])
    const sensor = { ...wican('mopeka-t1', 'Front tank'), kind: 'generic_mqtt' } as unknown as LiveLinkDevice
    render(<SensorBlock device={sensor} vehicles={[]} onChanged={vi.fn()} />)

    const toggle = screen.getByRole('button', { name: 'Advanced: topic mappings for Front tank' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('combobox', { name: 'Vehicle for Front tank' })).toBeInTheDocument()
  })
})

describe('TorqueSettingsDrawer names', () => {
  it('names the copy and show buttons beside the revealed URL and token', async () => {
    svc.getDevices.mockResolvedValue({ total: 0, online_count: 0, devices: [] })
    svc.createTorqueSource.mockResolvedValue({
      device_id: 'tq_new',
      upload_url: 'https://garage/api/v1/torque/tok/upload',
      token: 'tok',
    })
    const tab = { id: 'torque', label: 'Torque', kind: 'torque' } as unknown as IntegrationTab
    render(<TorqueSettingsDrawer open tab={tab} onClose={vi.fn()} onChanged={vi.fn()} />)
    await screen.findAllByRole('option', { name: 'Mirage' })
    fireEvent.change(screen.getByRole('combobox', { name: 'Vehicle' }), { target: { value: VEHICLE.vin } })
    fireEvent.click(screen.getByRole('button', { name: 'Create' }))

    expect(await screen.findByRole('button', { name: 'Copy Upload URL' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Copy Device Token' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Show Device Token' }))
    expect(screen.getByRole('button', { name: 'Hide Device Token' })).toBeInTheDocument()
  })
})

describe('WicanSettingsDrawer names', () => {
  it('says what each copy button copies, and names show/hide', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    svc.getSettings.mockResolvedValue({
      enabled: true,
      has_global_token: true,
      ingestion_url: 'http://garage/api/v1/livelink/ingest',
      firmware_check_enabled: true,
    })
    svc.getDevices.mockResolvedValue({ total: 0, online_count: 0, devices: [] })
    svc.getFirmwareLatest.mockResolvedValue({ latest_tag: 'v4.51p', release_url: null })
    svc.getDeviceFirmwareStatus.mockResolvedValue([])
    svc.getMQTTSettings.mockResolvedValue({ enabled: true, topic_prefix: 'wican' })
    svc.getMQTTStatus.mockResolvedValue({ running: true, connection_status: 'connected' })
    svc.regenerateGlobalToken.mockResolvedValue({ token: 'tok-123' })
    const tab = { id: 'wican', label: 'WiCAN', kind: 'wican' } as unknown as IntegrationTab
    render(<WicanSettingsDrawer open tab={tab} onClose={vi.fn()} onChanged={vi.fn()} />)

    expect(await screen.findByRole('button', { name: 'Copy Ingestion URL' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Regenerate' }))
    expect(await screen.findByRole('button', { name: 'Copy Global API Token' })).toBeInTheDocument()
    // A fresh global token arrives shown.
    fireEvent.click(screen.getByRole('button', { name: 'Hide Global API Token' }))
    expect(screen.getByRole('button', { name: 'Show Global API Token' })).toBeInTheDocument()
  })
})
