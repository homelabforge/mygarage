import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import type { IntegrationTab } from '@/types/livelink'

const svc = vi.hoisted(() => ({
  getDevices: vi.fn(),
  createTorqueSource: vi.fn(),
  listSources: vi.fn(),
  getDeviceParamKeys: vi.fn(),
}))
vi.mock('@/services/livelinkService', () => ({ livelinkService: svc }))
const VEHICLE = { vin: 'ML32A5HJ9KH009478', nickname: 'Mirage', year: 2019, make: 'Mitsubishi', model: 'Mirage' }
vi.mock('@/services/vehicleService', () => ({
  vehicleService: { list: () => Promise.resolve({ vehicles: [VEHICLE], total: 1 }) },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import TorqueSettingsDrawer from '../TorqueSettingsDrawer'
import { withConfirm } from '../../../../__tests__/confirmHelpers'

const TAB = { id: 'torque', label: 'Torque', kind: 'torque' } as unknown as IntegrationTab
const device = (id: string, kind: string) => ({
  device_id: id,
  kind,
  label: id,
  vin: null,
  enabled: true,
  device_status: 'unknown',
  ecu_status: 'unknown',
  sta_ip: null,
  has_device_token: true,
})

beforeEach(() => {
  vi.clearAllMocks()
  svc.getDevices.mockResolvedValue({
    total: 2,
    online_count: 0,
    devices: [device('tq_7dca3766', 'torque'), device('wican1', 'wican')],
  })
  svc.createTorqueSource.mockResolvedValue({
    device_id: 'tq_new',
    upload_url: 'https://garage/api/v1/torque/tok/upload',
    token: 'tok',
  })
  svc.listSources.mockResolvedValue([])
  svc.getDeviceParamKeys.mockResolvedValue([])
})

describe('TorqueSettingsDrawer', () => {
  it('lists only Torque sources, and warns about metric units', async () => {
    render(<TorqueSettingsDrawer open tab={TAB} onClose={vi.fn()} onChanged={vi.fn()} />, { wrapper: withConfirm })

    expect(await screen.findByText('tq_7dca3766', { selector: 'button' })).toBeInTheDocument()
    expect(screen.queryByText('wican1')).not.toBeInTheDocument()
    expect(screen.getByText('modal.torque.metricWarning')).toBeInTheDocument()
  })

  it('needs a vehicle before it can create a source, then reveals its URL and token', async () => {
    const onChanged = vi.fn()
    render(<TorqueSettingsDrawer open tab={TAB} onClose={vi.fn()} onChanged={onChanged} />, { wrapper: withConfirm })
    const create = await screen.findByRole('button', { name: 'modal.torque.create' })
    expect(create).toBeDisabled()

    await screen.findAllByRole('option', { name: 'Mirage' })
    fireEvent.change(screen.getByLabelText('settings:integrations.sourceVehicle'), {
      target: { value: VEHICLE.vin },
    })
    fireEvent.change(screen.getByLabelText('modal.torque.addLabel'), { target: { value: 'Phone' } })
    fireEvent.click(create)

    await waitFor(() => expect(svc.createTorqueSource).toHaveBeenCalledWith(VEHICLE.vin, 'Phone'))
    expect(await screen.findByDisplayValue('https://garage/api/v1/torque/tok/upload')).toBeInTheDocument()
    expect(screen.getByDisplayValue('tok')).toBeInTheDocument()
    expect(onChanged).toHaveBeenCalled()
  })

  it('does not show a revealed token again after reopening', async () => {
    // The token is shown once; the server keeps only its hash.
    const { rerender } = render(<TorqueSettingsDrawer open tab={TAB} onClose={vi.fn()} onChanged={vi.fn()} />, { wrapper: withConfirm })
    await screen.findAllByRole('option', { name: 'Mirage' })
    fireEvent.change(screen.getByLabelText('settings:integrations.sourceVehicle'), {
      target: { value: VEHICLE.vin },
    })
    fireEvent.click(screen.getByRole('button', { name: 'modal.torque.create' }))
    expect(await screen.findByDisplayValue('tok')).toBeInTheDocument()

    rerender(<TorqueSettingsDrawer open={false} tab={TAB} onClose={vi.fn()} onChanged={vi.fn()} />)
    rerender(<TorqueSettingsDrawer open tab={TAB} onClose={vi.fn()} onChanged={vi.fn()} />)

    await screen.findByRole('button', { name: 'modal.torque.create' })
    expect(screen.queryByDisplayValue('tok')).not.toBeInTheDocument()
  })
})
