import type { ComponentProps } from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, fireEvent, waitFor, within } from '@testing-library/react'
import { render } from '../../../__tests__/test-utils'
import type { Vehicle } from '../../../types/vehicle'
import vehicleService from '../../../services/vehicleService'

vi.mock('../../../services/vehicleService', () => ({
  default: { update: vi.fn() },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const unitPrefMock = vi.hoisted(() => ({
  system: 'metric' as 'metric' | 'imperial',
  showBoth: false,
}))
vi.mock('../../../hooks/useUnitPreference', () => ({
  useUnitPreference: () => unitPrefMock,
}))

import VehicleSpecsPanel from '../VehicleSpecsPanel'
import { toast } from 'sonner'

const mockedUpdate = vi.mocked(vehicleService).update

const baseVehicle = {
  vin: 'TEST0000000000001',
  nickname: 'Test',
  vehicle_type: 'Car',
  usage_unit: 'distance',
  secondary_usage_enabled: false,
  oil_viscosity: '5W-30',
  oil_capacity_liters: '4.7',
  lug_nut_torque_nm: '135.0',
  oil_filter_part_number: null,
  coolant_type: null,
  brake_fluid_type: null,
  transmission_fluid_type: null,
  maintenance_specs_notes: null,
} as unknown as Vehicle

function renderPanel(props: Partial<ComponentProps<typeof VehicleSpecsPanel>> = {}) {
  const onUpdated = vi.fn()
  render(
    <VehicleSpecsPanel
      vin="TEST0000000000001"
      vehicle={baseVehicle}
      onUpdated={onUpdated}
      {...props}
    />,
  )
  return { onUpdated }
}

describe('VehicleSpecsPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    unitPrefMock.system = 'metric'
    mockedUpdate.mockResolvedValue(baseVehicle)
  })

  it('shows recorded oil viscosity and torque on the card', () => {
    renderPanel()
    expect(screen.getByText('detail.specs.title')).toBeInTheDocument()
    expect(screen.getByText('5W-30')).toBeInTheDocument()
  })

  it('opens the editor drawer from the card overlay', async () => {
    renderPanel()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'detail.specs.editAria' }))
    const drawer = await screen.findByRole('dialog')
    expect(drawer).toHaveAccessibleName('detail.specs.title')
    expect(within(drawer).getByLabelText('detail.specs.oilViscosity')).toHaveValue('5W-30')
  })

  it('opens when editRequestKey increments', async () => {
    const { rerender } = render(
      <VehicleSpecsPanel
        vin="TEST0000000000001"
        vehicle={baseVehicle}
        onUpdated={vi.fn()}
        editRequestKey={0}
      />,
    )
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    rerender(
      <VehicleSpecsPanel
        vin="TEST0000000000001"
        vehicle={baseVehicle}
        onUpdated={vi.fn()}
        editRequestKey={1}
      />,
    )
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
  })

  it('saves oil viscosity via partial PUT and closes', async () => {
    const { onUpdated } = renderPanel()
    fireEvent.click(screen.getByRole('button', { name: 'detail.specs.editAria' }))
    const drawer = await screen.findByRole('dialog')
    fireEvent.change(within(drawer).getByLabelText('detail.specs.oilViscosity'), {
      target: { value: '0W-20' },
    })
    fireEvent.click(within(drawer).getByRole('button', { name: 'common:save' }))

    await waitFor(() => expect(mockedUpdate).toHaveBeenCalledTimes(1))
    const [, payload] = mockedUpdate.mock.calls[0]
    expect(payload.oil_viscosity).toBe('0W-20')
    expect(payload.oil_capacity_liters).toBeCloseTo(4.7, 1)
    expect(payload.lug_nut_torque_nm).toBeCloseTo(135, 0)
    await waitFor(() => expect(onUpdated).toHaveBeenCalledWith(baseVehicle))
    expect(toast.success).toHaveBeenCalled()
  })

  it('shows empty state when no specs are set', () => {
    renderPanel({
      vehicle: {
        ...baseVehicle,
        oil_viscosity: null,
        oil_capacity_liters: null,
        lug_nut_torque_nm: null,
      } as Vehicle,
    })
    expect(screen.getByText('detail.specs.empty')).toBeInTheDocument()
  })
})
