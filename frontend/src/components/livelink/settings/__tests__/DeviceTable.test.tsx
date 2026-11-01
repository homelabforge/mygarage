/**
 * DeviceTable owns the per-device actions a drawer offers, and tells the
 * drawer when something changed so it can reload and refresh the card.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import type { LiveLinkDevice } from '@/types/livelink'

const listSources = vi.fn()
const deleteDevice = vi.fn()
const updateDevice = vi.fn()
const setSdConfig = vi.fn()
const triggerSdBackfill = vi.fn()
vi.mock('@/services/livelinkService', () => ({
  livelinkService: {
    listSources: () => listSources(),
    deleteDevice: (id: string) => deleteDevice(id),
    updateDevice: (id: string, u: unknown) => updateDevice(id, u),
    setSdConfig: (id: string, c: unknown) => setSdConfig(id, c),
    triggerSdBackfill: (id: string) => triggerSdBackfill(id),
    getDeviceParamKeys: () => Promise.resolve([]),
  },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() } }))

import { toast } from 'sonner'
import DeviceTable from '../DeviceTable'

/** What axios rejects with, as far as the error helpers read it. */
const httpError = (status: number, detail: string): Error =>
  Object.assign(new Error(`Request failed with status code ${status}`), {
    isAxiosError: true,
    response: { status, data: { detail } },
  })

const make = (id: string): LiveLinkDevice =>
  ({
    device_id: id,
    kind: 'wican',
    label: id,
    vin: null,
    enabled: true,
    device_status: 'offline',
    ecu_status: 'unknown',
    fw_version: '4.50',
    sta_ip: null,
    has_device_token: false,
  }) as unknown as LiveLinkDevice

beforeEach(() => {
  vi.clearAllMocks()
  listSources.mockResolvedValue([
    { kind: 'wican', capabilities: ['commands', 'odometer', 'sd_backfill', 'telemetry'], syncs_odometer: true },
  ])
  deleteDevice.mockResolvedValue(undefined)
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('DeviceTable', () => {
  it('deletes after confirmation, then tells the drawer', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const onChanged = vi.fn()
    render(<DeviceTable devices={[make('d1')]} vehicles={[]} onChanged={onChanged} />)

    fireEvent.click(screen.getByTitle('modal.livelink.deleteDevice'))

    await waitFor(() => expect(deleteDevice).toHaveBeenCalledWith('d1'))
    await waitFor(() => expect(onChanged).toHaveBeenCalled())
  })

  it('does nothing when the confirmation is declined', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    const onChanged = vi.fn()
    render(<DeviceTable devices={[make('d1')]} vehicles={[]} onChanged={onChanged} />)

    fireEvent.click(screen.getByTitle('modal.livelink.deleteDevice'))

    expect(deleteDevice).not.toHaveBeenCalled()
    expect(onChanged).not.toHaveBeenCalled()
  })

  it('asks for the source catalogue once, not once per row', async () => {
    render(
      <DeviceTable devices={[make('d1'), make('d2'), make('d3')]} vehicles={[]} onChanged={vi.fn()} />,
    )

    // The rows gain their capability-gated controls once it arrives.
    expect(await screen.findAllByTitle('modal.livelink.deviceSettings')).toHaveLength(3)
    expect(listSources).toHaveBeenCalledTimes(1)
  })

  it('puts a refused odometer unit back and says why', async () => {
    // The server refuses a unit change once readings depend on it.
    updateDevice.mockRejectedValue(httpError(409, 'Odometer history depends on this unit'))
    const onChanged = vi.fn()
    render(<DeviceTable devices={[make('d1')]} vehicles={[]} onChanged={onChanged} />)
    fireEvent.click(await screen.findByTitle('modal.livelink.deviceSettings'))
    const unit = screen.getByDisplayValue('modal.livelink.odometerUnitAuto')

    fireEvent.change(unit, { target: { value: 'mi' } })

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Odometer history depends on this unit'))
    await waitFor(() => expect(unit).toHaveValue('auto'))
    expect(onChanged).not.toHaveBeenCalled()
  })

  it("shows the server's reason when a device update is refused", async () => {
    // A 403, not a conflict: getErrorMessage would swap it for a generic line.
    updateDevice.mockRejectedValue(httpError(403, 'Only an admin can manage an unlinked device'))
    const vehicle = { vin: '1HGBH41JXMN109186', nickname: 'Durango', year: 2023, make: 'KZ', model: 'RV' }
    render(<DeviceTable devices={[make('d1')]} vehicles={[vehicle as never]} onChanged={vi.fn()} />)

    fireEvent.change(screen.getByRole('combobox', { name: 'modal.livelink.actionFor' }), { target: { value: vehicle.vin } })

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith('Only an admin can manage an unlinked device'),
    )
  })

  it("shows the server's reason when SD settings are refused", async () => {
    setSdConfig.mockRejectedValue(httpError(422, 'A torque device has no SD card'))
    render(<DeviceTable devices={[make('d1')]} vehicles={[]} onChanged={vi.fn()} />)
    fireEvent.click(await screen.findByTitle('modal.livelink.deviceSettings'))
    fireEvent.change(screen.getByPlaceholderText('192.168.1.x'), { target: { value: '10.0.0.5' } })

    fireEvent.click(screen.getByRole('button', { name: 'modal.livelink.save' }))

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('A torque device has no SD card'))
  })

  it("shows the server's reason when an SD pull is refused", async () => {
    triggerSdBackfill.mockRejectedValue(httpError(422, 'A torque device has no SD card to pull'))
    render(<DeviceTable devices={[make('d1')]} vehicles={[]} onChanged={vi.fn()} />)
    fireEvent.click(await screen.findByTitle('modal.livelink.deviceSettings'))

    fireEvent.click(screen.getByRole('button', { name: 'modal.livelink.pullSdLogsNow' }))

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('A torque device has no SD card to pull'))
  })

  // Regression guard (carry 6): a 409 shows its detail too, not a generic line.
  it('says LiveLink is switched off when an SD pull is refused for that', async () => {
    triggerSdBackfill.mockRejectedValue(httpError(409, 'LiveLink is switched off'))
    render(<DeviceTable devices={[make('d1')]} vehicles={[]} onChanged={vi.fn()} />)
    fireEvent.click(await screen.findByTitle('modal.livelink.deviceSettings'))

    fireEvent.click(screen.getByRole('button', { name: 'modal.livelink.pullSdLogsNow' }))

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('LiveLink is switched off'))
  })

  // Regression guard (FB-9): a device that's gone answers 404 now, not an
  // all-zero summary, and the toast already shows a 404's detail.
  it('names the missing device when an SD pull finds none', async () => {
    triggerSdBackfill.mockRejectedValue(httpError(404, 'Device d1 not found'))
    render(<DeviceTable devices={[make('d1')]} vehicles={[]} onChanged={vi.fn()} />)
    fireEvent.click(await screen.findByTitle('modal.livelink.deviceSettings'))

    fireEvent.click(screen.getByRole('button', { name: 'modal.livelink.pullSdLogsNow' }))

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Device d1 not found'))
    expect(toast.success).not.toHaveBeenCalled()
  })
})
