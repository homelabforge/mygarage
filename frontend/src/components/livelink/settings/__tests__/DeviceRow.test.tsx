/**
 * DeviceRow: the firmware cell (plan 2026-09-18, feature B), and which
 * controls each source kind is offered (sidecars plan, Task 4).
 *
 * The row used to show every control to every device, which was right only
 * while WiCAN was the only source. It is now gated by the source module's
 * declared capabilities, plus three WiCAN wire features by kind.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import type { ComponentProps } from 'react'
import type { DeviceFirmwareStatus, LiveLinkDevice } from '@/types/livelink'
import type { SourceInfo } from '@/types/livelinkTopicMap'
import type { Vehicle } from '@/types/vehicle'

const getDeviceParamKeys = vi.fn()
vi.mock('@/services/livelinkService', () => ({
  livelinkService: { getDeviceParamKeys: (id: string) => getDeviceParamKeys(id) },
}))

import DeviceRow from '../DeviceRow'

const device = {
  device_id: 'aabbccddeeff',
  kind: 'wican',
  label: 'Truck dongle',
  vin: null,
  enabled: true,
  device_status: 'online',
  online: true,
  last_seen: '2026-10-24T10:00:00Z',
  ecu_status: 'offline',
  hw_version: 'WiCAN-OBD-PRO',
  fw_version: '4.45',
  sta_ip: null,
  has_device_token: false,
  device_address: null,
  sd_backfill_enabled: false,
  odometer_unit: null,
} as unknown as LiveLinkDevice

const VEHICLE = { vin: '1HGBH41JXMN109186', nickname: 'Durango', year: 2023, make: 'KZ', model: 'RV' } as Vehicle

const WICAN: SourceInfo = {
  kind: 'wican',
  capabilities: ['commands', 'odometer', 'sd_backfill', 'telemetry'],
  syncs_odometer: true,
}
const TORQUE: SourceInfo = {
  kind: 'torque',
  capabilities: ['drive_session', 'location', 'odometer', 'telemetry'],
  syncs_odometer: false,
}
const GENERIC: SourceInfo = { kind: 'generic_mqtt', capabilities: ['telemetry'], syncs_odometer: false }

const firmware = (overrides: Partial<DeviceFirmwareStatus>): DeviceFirmwareStatus =>
  ({
    device_id: device.device_id,
    current_version: '4.45',
    latest_version: '4.50',
    update_available: true,
    release_url: null,
    firmware_track: 'pro',
    skipped_version: null,
    ...overrides,
  }) as DeviceFirmwareStatus

const onSkipFirmware = vi.fn()
const onUnskipFirmware = vi.fn()

function renderRow(
  deviceFirmware?: DeviceFirmwareStatus,
  overrides: Partial<ComponentProps<typeof DeviceRow>> = {},
) {
  return render(
    <table>
      <tbody>
        <DeviceRow
          device={device}
          vehicles={[]}
          source={WICAN}
          showFirmware
          deviceFirmware={deviceFirmware}
          mqttConnected={false}
          onUpdate={vi.fn()}
          onDelete={vi.fn()}
          onGenerateToken={vi.fn()}
          onRevokeToken={vi.fn()}
          onSendCommand={vi.fn()}
          onSetSdConfig={vi.fn()}
          onSdBackfill={vi.fn()}
          onSkipFirmware={onSkipFirmware}
          onUnskipFirmware={onUnskipFirmware}
          {...overrides}
        />
      </tbody>
    </table>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  getDeviceParamKeys.mockResolvedValue([])
})

describe('DeviceRow firmware cell', () => {
  it('an available update shows the badge and the skip action passes the version the client saw', () => {
    renderRow(firmware({}))
    expect(screen.getByText('modal.livelink.updateBadge')).toBeInTheDocument()
    fireEvent.click(screen.getByTitle('modal.livelink.skipVersion'))
    expect(onSkipFirmware).toHaveBeenCalledWith('aabbccddeeff', '4.50')
  })

  it('a skipped latest version shows the muted pill + unskip instead of the badge', () => {
    renderRow(firmware({ skipped_version: '4.50' }))
    expect(screen.getByText('modal.livelink.skippedBadge')).toBeInTheDocument()
    expect(screen.queryByText('modal.livelink.updateBadge')).not.toBeInTheDocument()
    expect(screen.queryByTitle('modal.livelink.skipVersion')).not.toBeInTheDocument()
    fireEvent.click(screen.getByTitle('modal.livelink.unskip'))
    expect(onUnskipFirmware).toHaveBeenCalledWith('aabbccddeeff')
  })

  it('a stale skip (an even newer release arrived) shows the badge again', () => {
    renderRow(firmware({ skipped_version: '4.50', latest_version: '4.51' }))
    expect(screen.getByText('modal.livelink.updateBadge')).toBeInTheDocument()
    expect(screen.queryByText('modal.livelink.skippedBadge')).not.toBeInTheDocument()
  })

  it('no update means no badge, no pill and no skip action', () => {
    renderRow(firmware({ update_available: false }))
    expect(screen.queryByText('modal.livelink.updateBadge')).not.toBeInTheDocument()
    expect(screen.queryByText('modal.livelink.skippedBadge')).not.toBeInTheDocument()
    expect(screen.queryByTitle('modal.livelink.skipVersion')).not.toBeInTheDocument()
  })
})

describe('DeviceRow controls by source', () => {
  it('offers a WiCAN every control it offered before', () => {
    // The positive control for the two tests below: gating must not take
    // anything away from the source these controls were built for.
    renderRow(undefined, { mqttConnected: true })
    expect(screen.getByText(/modal.livelink.ecuLabel/)).toBeInTheDocument()
    expect(screen.getByTitle('modal.livelink.generateDeviceToken')).toBeInTheDocument()
    expect(screen.getByTitle('modal.livelink.checkBatteryVoltage')).toBeInTheDocument()
    fireEvent.click(screen.getByTitle('modal.livelink.deviceSettings'))
    expect(screen.getByText('modal.livelink.deviceAddress')).toBeInTheDocument()
    expect(screen.getByText('modal.livelink.odometerUnit')).toBeInTheDocument()
  })

  it('shows a Torque source none of the WiCAN wire controls', () => {
    renderRow(undefined, {
      device: { ...device, kind: 'torque', device_status: 'unknown' },
      source: TORQUE,
      mqttConnected: true,
      showFirmware: false,
    })
    expect(screen.queryByText(/modal.livelink.ecuLabel/)).not.toBeInTheDocument()
    // Its token IS its upload URL: regenerating it here would break the phone.
    expect(screen.queryByTitle('modal.livelink.generateDeviceToken')).not.toBeInTheDocument()
    expect(screen.queryByTitle('modal.livelink.checkBatteryVoltage')).not.toBeInTheDocument()
    // Torque declares ODOMETER, so its odometer settings stay reachable; SD
    // backfill is not among them.
    fireEvent.click(screen.getByTitle('modal.livelink.deviceSettings'))
    expect(screen.getByText('modal.livelink.odometerUnit')).toBeInTheDocument()
    expect(screen.queryByText('modal.livelink.deviceAddress')).not.toBeInTheDocument()
  })

  it('offers a generic MQTT device no device-settings panel at all', () => {
    renderRow(undefined, {
      device: { ...device, kind: 'generic_mqtt' },
      source: GENERIC,
      showFirmware: false,
    })
    expect(screen.queryByTitle('modal.livelink.deviceSettings')).not.toBeInTheDocument()
  })

  it('unlinks with an empty VIN, which the API reads as "clear"', () => {
    const onUpdate = vi.fn()
    renderRow(undefined, { device: { ...device, vin: VEHICLE.vin }, vehicles: [VEHICLE], onUpdate })
    fireEvent.change(screen.getByRole('combobox', { name: 'modal.vehicle' }), {
      target: { value: '' },
    })
    expect(onUpdate).toHaveBeenCalledWith(device.device_id, { vin: '' })
  })
})

describe('DeviceRow label', () => {
  it('clearing the label sends null, which clears it', () => {
    const onUpdate = vi.fn()
    renderRow(undefined, { onUpdate })
    fireEvent.click(screen.getByRole('button', { name: 'Truck dongle' }))
    const input = screen.getByPlaceholderText('modal.livelink.labelPlaceholder')
    fireEvent.change(input, { target: { value: '' } })
    fireEvent.click(input.nextElementSibling as HTMLElement)
    expect(onUpdate).toHaveBeenCalledWith(device.device_id, { label: null })
  })
})

describe('DeviceRow status line', () => {
  // The vitest mock hands keys back as written, so a key here is a label the
  // row looked up rather than a raw status it printed.
  const statusLine = (): HTMLElement =>
    screen.getByText(/^forms:modal\.livelink\.deviceStatus\./).closest('span') as HTMLElement

  it('reads an uploading Torque phone as online, though it never reports a status', () => {
    renderRow(undefined, {
      device: { ...device, kind: 'torque', device_status: 'unknown', online: true },
      source: TORQUE,
      showFirmware: false,
    })
    expect(statusLine()).toHaveTextContent('forms:modal.livelink.deviceStatus.online')
    expect(statusLine()).toHaveClass('text-green-500')
    expect(screen.queryByText('unknown')).not.toBeInTheDocument()
  })

  it('reads a disabled device as offline, whatever status it froze at', () => {
    renderRow(undefined, { device: { ...device, device_status: 'online', online: false } })
    expect(statusLine()).toHaveTextContent('forms:modal.livelink.deviceStatus.offline')
    expect(statusLine()).toHaveClass('text-red-500')
  })

  it('says a device that has never reported has no status yet, not that it is offline', () => {
    renderRow(undefined, {
      device: { ...device, device_status: 'unknown', online: false, last_seen: null },
    })
    expect(statusLine()).toHaveTextContent('forms:modal.livelink.deviceStatus.unknown')
    expect(statusLine()).toHaveClass('text-gray-500')
  })

  it('translates the ECU line', () => {
    renderRow()
    expect(screen.getByText(/modal\.livelink\.ecuLabel/)).toHaveTextContent(
      'modal.livelink.ecuLabel forms:modal.livelink.ecuStatus.offline',
    )
  })

  it('offers no battery check to a device that is not online, whatever status it froze at', () => {
    renderRow(undefined, { mqttConnected: true, device: { ...device, device_status: 'online', online: false } })
    expect(screen.queryByTitle('modal.livelink.checkBatteryVoltage')).not.toBeInTheDocument()
  })
})

describe('DeviceRow refused settings', () => {
  // DeviceTable resolves false when the PUT fails (a 409 when readings depend
  // on the unit). The select must go back to what the device really has.
  it('puts the odometer unit back when the update is refused', async () => {
    const onUpdate = vi.fn().mockResolvedValue(false)
    renderRow(undefined, { device: { ...device, odometer_unit: 'km' }, onUpdate })
    fireEvent.click(screen.getByTitle('modal.livelink.deviceSettings'))
    const unit = screen.getByDisplayValue('modal.livelink.odometerUnitKm')

    fireEvent.change(unit, { target: { value: 'mi' } })

    expect(onUpdate).toHaveBeenCalledWith(device.device_id, { odometer_unit: 'mi' })
    await waitFor(() => expect(unit).toHaveValue('km'))
  })

  it('keeps the odometer unit when the update goes through', async () => {
    // Regression guard: the revert above must not undo a change that saved.
    const onUpdate = vi.fn().mockResolvedValue(true)
    renderRow(undefined, { device: { ...device, odometer_unit: 'km' }, onUpdate })
    fireEvent.click(screen.getByTitle('modal.livelink.deviceSettings'))
    const unit = screen.getByDisplayValue('modal.livelink.odometerUnitKm')

    fireEvent.change(unit, { target: { value: 'mi' } })

    await waitFor(() => expect(onUpdate).toHaveBeenCalled())
    expect(unit).toHaveValue('mi')
  })

  it('puts the odometer parameter back when the update is refused', async () => {
    getDeviceParamKeys.mockResolvedValue(['ODO', 'DISTANCE'])
    const onUpdate = vi.fn().mockResolvedValue(false)
    renderRow(undefined, {
      device: { ...device, kind: 'torque', odometer_param_key: 'ODO' },
      source: TORQUE,
      showFirmware: false,
      onUpdate,
    })
    fireEvent.click(screen.getByTitle('modal.livelink.deviceSettings'))
    const param = await screen.findByDisplayValue('ODO')

    fireEvent.change(param, { target: { value: 'DISTANCE' } })

    expect(onUpdate).toHaveBeenCalledWith(device.device_id, { odometer_param_key: 'DISTANCE' })
    await waitFor(() => expect(param).toHaveValue('ODO'))
  })
})
