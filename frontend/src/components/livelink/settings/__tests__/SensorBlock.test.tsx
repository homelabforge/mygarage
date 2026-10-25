import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import type { ReactNode } from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import type { LiveLinkDevice } from '@/types/livelink'
import settingsEn from '../../../../locales/en/settings.json'

// The delete prompt renders the way en reads, since what name it shows is
// the point of a test below. Every other key stays bare, like the global mock.
vi.mock('react-i18next', () => {
  const t = (key: string, options?: Record<string, unknown>): string =>
    key === 'integrations.confirmDeleteSensor'
      ? settingsEn.integrations.confirmDeleteSensor.replace('{{name}}', String(options?.name))
      : key
  return {
    useTranslation: () => ({ t, i18n: { language: 'en', changeLanguage: () => Promise.resolve() } }),
    Trans: ({ children }: { children: ReactNode }) => children,
    initReactI18next: { type: '3rdParty', init: () => {} },
  }
})

const svc = vi.hoisted(() => ({
  getDeviceReadings: vi.fn(),
  updateDevice: vi.fn(),
  deleteDevice: vi.fn(),
  listTopicMaps: vi.fn(),
}))
vi.mock('@/services/livelinkService', () => ({ livelinkService: svc }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
// The list has its own suite; here only what the block hands it matters.
vi.mock('../DeviceReadingsList', () => ({
  default: ({ sensorLabel, compact }: { sensorLabel?: string; compact?: boolean }) => (
    <p>
      readings for {sensorLabel} {compact ? 'compact' : 'full'}
    </p>
  ),
}))

// Its own suite too: here, that it gets the readings and a save reloads them.
vi.mock('../SensorAlerts', () => ({
  default: ({ readings, sensorLabel, onSaved }: { readings: unknown[]; sensorLabel?: string; onSaved: () => void }) => (
    <button type="button" onClick={onSaved}>
      alerts for {sensorLabel} over {readings.length}
    </button>
  ),
}))

import SensorBlock from '../SensorBlock'

const VEHICLE = { vin: '4EZFD3821P6080615', nickname: 'Durango', year: 2023, make: 'KZ', model: 'Durango' }
const sensor = (overrides: Partial<LiveLinkDevice> = {}): LiveLinkDevice =>
  ({
    device_id: 'mopeka-t1',
    kind: 'generic_mqtt',
    label: 'Front tank',
    vin: VEHICLE.vin,
    preset_key: 'mopeka',
    enabled: true,
    device_status: 'unknown',
    ...overrides,
  }) as unknown as LiveLinkDevice

const renderBlock = (device = sensor()) => {
  const onChanged = vi.fn()
  render(<SensorBlock device={device} vehicles={[VEHICLE as never]} onChanged={onChanged} />)
  return { onChanged }
}

beforeEach(() => {
  vi.clearAllMocks()
  svc.getDeviceReadings.mockResolvedValue({ device_id: 'mopeka-t1', vin: VEHICLE.vin, online: true, readings: [] })
  svc.updateDevice.mockResolvedValue({})
  svc.deleteDevice.mockResolvedValue(undefined)
  svc.listTopicMaps.mockResolvedValue([])
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('SensorBlock', () => {
  it('names the sensor and hands its readings over compactly', async () => {
    renderBlock()

    expect(screen.getByRole('heading', { name: /Front tank/ })).toBeInTheDocument()
    expect(await screen.findByText('readings for Front tank compact')).toBeInTheDocument()
  })

  it.each([
    [{ vin: null }, true, 'integrations.sourceVehicleUnset'],
    [{}, true, 'integrations.statusReceiving'],
    [{}, false, 'integrations.sensorNoData'],
  ])('states its own status (%j, online=%s)', async (overrides, online, word) => {
    svc.getDeviceReadings.mockResolvedValue({ device_id: 'mopeka-t1', vin: null, online, readings: [] })
    renderBlock(sensor(overrides as Partial<LiveLinkDevice>))

    // "Not linked" is also the vehicle picker's empty option; the status is
    // the one that is not an <option>.
    const found = await screen.findAllByText(word)
    expect(found.filter((el) => el.tagName !== 'OPTION')).toHaveLength(1)
  })

  it('reads neutral while its readings load, not "no recent readings"', () => {
    svc.getDeviceReadings.mockReturnValue(new Promise(() => {}))
    renderBlock()

    expect(screen.queryByText('integrations.sensorNoData')).not.toBeInTheDocument()
    expect(screen.getByText('integrations.sensorStatusLoading')).toHaveClass('text-text-mute')
  })

  it('says the readings failed to load, not that the sensor is quiet', async () => {
    svc.getDeviceReadings.mockRejectedValue(new Error('boom'))
    renderBlock()

    // The body's own error line shows once the load has failed.
    await screen.findByText('integrations.readingsLoadError')
    expect(screen.queryByText('integrations.sensorNoData')).not.toBeInTheDocument()
    expect(screen.getByText('integrations.sensorStatusFailed')).toBeInTheDocument()
  })

  it('hands its readings to the alert lines, and reloads them after a save', async () => {
    const readings = [{ param_key: 'PROPANE_T1_LEVEL_PCT' }, { param_key: 'PROPANE_T1_TEMP_C' }]
    svc.getDeviceReadings.mockResolvedValue({ device_id: 'mopeka-t1', vin: VEHICLE.vin, online: true, readings })
    renderBlock()

    fireEvent.click(await screen.findByRole('button', { name: 'alerts for Front tank over 2' }))

    await waitFor(() => expect(svc.getDeviceReadings).toHaveBeenCalledTimes(2))
  })

  it('renames the sensor and refreshes its readings, whose names follow', async () => {
    const { onChanged } = renderBlock()
    await screen.findByText('readings for Front tank compact')

    fireEvent.click(screen.getByRole('button', { name: 'integrations.renameSensor' }))
    fireEvent.change(screen.getByLabelText('integrations.sensorName'), { target: { value: 'Rear tank' } })
    fireEvent.click(screen.getByRole('button', { name: 'forms:modal.livelink.save' }))

    await waitFor(() => expect(svc.updateDevice).toHaveBeenCalledWith('mopeka-t1', { label: 'Rear tank' }))
    expect(onChanged).toHaveBeenCalled()
    await waitFor(() => expect(svc.getDeviceReadings).toHaveBeenCalledTimes(2))
  })

  it('cannot save a blank name', async () => {
    // Every reading is named after the sensor.
    renderBlock()
    await screen.findByText('readings for Front tank compact')

    fireEvent.click(screen.getByRole('button', { name: 'integrations.renameSensor' }))
    fireEvent.change(screen.getByLabelText('integrations.sensorName'), { target: { value: '   ' } })

    expect(screen.getByRole('button', { name: 'forms:modal.livelink.save' })).toBeDisabled()
  })

  it('links it to a vehicle, and unlinks with an empty VIN', async () => {
    renderBlock()
    const picker = await screen.findByRole('combobox', { name: 'integrations.sourceVehicle' })

    fireEvent.change(picker, { target: { value: '' } })

    await waitFor(() => expect(svc.updateDevice).toHaveBeenCalledWith('mopeka-t1', { vin: '' }))
  })

  it('deletes after confirmation', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const { onChanged } = renderBlock()

    fireEvent.click(await screen.findByRole('button', { name: 'integrations.deleteSensor' }))

    await waitFor(() => expect(svc.deleteDevice).toHaveBeenCalledWith('mopeka-t1'))
    expect(onChanged).toHaveBeenCalled()
  })

  it('names a sensor with a stored blank label by its device id in the delete prompt', async () => {
    // A name cleared before blanks were stored as null is still '' in the row.
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    renderBlock(sensor({ label: '' }))

    fireEvent.click(await screen.findByRole('button', { name: 'integrations.deleteSensor' }))

    expect(confirm).toHaveBeenCalledWith('Delete mopeka-t1 and all of its readings? This cannot be undone.')
  })

  it('keeps the sensor when the confirmation is declined', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    renderBlock()

    fireEvent.click(await screen.findByRole('button', { name: 'integrations.deleteSensor' }))

    expect(svc.deleteDevice).not.toHaveBeenCalled()
  })
})
