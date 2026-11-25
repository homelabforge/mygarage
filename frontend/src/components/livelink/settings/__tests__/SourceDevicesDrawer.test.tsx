import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import type { IntegrationTab } from '@/types/livelink'

const svc = vi.hoisted(() => ({
  getDevices: vi.fn(),
  listSources: vi.fn(),
  getDeviceParamKeys: vi.fn(),
}))
vi.mock('@/services/livelinkService', () => ({ livelinkService: svc }))
vi.mock('@/services/vehicleService', () => ({
  vehicleService: { list: () => Promise.resolve({ vehicles: [], total: 0 }) },
}))

import SourceDevicesDrawer from '../SourceDevicesDrawer'
import { withConfirm } from '../../../../__tests__/confirmHelpers'

const device = (id: string, kind: string) => ({
  device_id: id,
  kind,
  label: id,
  vin: null,
  enabled: true,
  device_status: 'unknown',
  ecu_status: 'unknown',
  sta_ip: null,
  has_device_token: false,
})

beforeEach(() => {
  vi.clearAllMocks()
  svc.getDevices.mockResolvedValue({
    total: 2,
    online_count: 0,
    devices: [device('obd1', 'obdlink'), device('wican1', 'wican')],
  })
  svc.listSources.mockResolvedValue([])
  svc.getDeviceParamKeys.mockResolvedValue([])
})

describe('SourceDevicesDrawer', () => {
  it("lists only its own kind's devices, under the tab's name", async () => {
    // A newly registered module with no bespoke drawer still gets one.
    const tab = { id: 'obdlink', label: 'obdlink', kind: 'obdlink' } as unknown as IntegrationTab
    render(<SourceDevicesDrawer open tab={tab} onClose={vi.fn()} onChanged={vi.fn()} />, { wrapper: withConfirm })

    expect(await screen.findByText('obd1', { selector: 'button' })).toBeInTheDocument()
    expect(screen.queryByText('wican1')).not.toBeInTheDocument()
    expect(screen.getByRole('dialog', { name: 'integrations.sourceSettings' })).toBeInTheDocument()
  })
})
