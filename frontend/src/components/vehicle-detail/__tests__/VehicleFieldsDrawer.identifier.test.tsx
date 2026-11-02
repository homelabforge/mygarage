import type { ComponentProps } from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, fireEvent, waitFor } from '@testing-library/react'
import { render } from '../../../__tests__/test-utils'
import VehicleFieldsDrawer from '../VehicleFieldsDrawer'
import vehicleService from '../../../services/vehicleService'
import type { Vehicle } from '../../../types/vehicle'

vi.mock('../../../services/vehicleService', () => ({
  default: { update: vi.fn() },
}))
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }))

import { toast } from 'sonner'

const mockedUpdate = vi.mocked(vehicleService).update

// The identifier on the Basic Information sidecar (#226).
const withVin = {
  vin: '1FTFW1E50NFA00001',
  nickname: 'F-150',
  identifier_type: 'vin',
  identifier: null,
  has_vin: true,
  year: 2022,
} as unknown as Vehicle

const qKeyed = {
  vin: 'QABCDEFGH12345678',
  nickname: 'Kubota',
  identifier_type: 'serial',
  identifier: 'KBT-1',
  has_vin: false,
  year: 2019,
} as unknown as Vehicle

function renderDrawer(vehicle: Vehicle, props: Partial<ComponentProps<typeof VehicleFieldsDrawer>> = {}) {
  const onUpdated = vi.fn()
  const onClose = vi.fn()
  render(
    <VehicleFieldsDrawer
      open
      onClose={onClose}
      vehicle={vehicle}
      vin={vehicle.vin}
      card="basic"
      onUpdated={onUpdated}
      {...props}
    />,
  )
  return { onUpdated, onClose }
}

const typeSelect = (): HTMLSelectElement => screen.getByLabelText('identifier.typeLabel') as HTMLSelectElement
const vinOption = (): HTMLOptionElement =>
  Array.from(typeSelect().options).find((o) => o.value === 'vin') as HTMLOptionElement
const save = (): void => {
  fireEvent.click(screen.getByRole('button', { name: 'common:save' }))
}

describe('VehicleFieldsDrawer: identifier (#226)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedUpdate.mockImplementation(async (_vin, data) => ({ ...withVin, ...data }) as Vehicle)
  })

  it('a VIN vehicle seeds type vin, hides the identifier and can pick any type', () => {
    renderDrawer(withVin)
    expect(typeSelect()).toHaveValue('vin')
    expect(Array.from(typeSelect().options).map((o) => o.value)).toEqual([
      'vin', 'serial', 'hin', 'chassis', 'asset_tag', 'none',
    ])
    expect(Array.from(typeSelect().options).some((o) => o.disabled)).toBe(false)
    expect(screen.queryByLabelText('identifier.valueLabel')).not.toBeInTheDocument()
    expect(screen.queryByText('identifier.cannotAddVin')).not.toBeInTheDocument()
  })

  it('a vehicle keyed by a generated key can never pick vin, and says why', () => {
    renderDrawer(qKeyed)
    expect(typeSelect()).toHaveValue('serial')
    expect(vinOption().disabled).toBe(true)
    expect(screen.getByText('identifier.cannotAddVin')).toBeInTheDocument()
    expect(screen.getByLabelText('identifier.valueLabel')).toHaveValue('KBT-1')
  })

  it('a serial with a VIN-shaped key (the fake-VIN workaround) may switch back to vin', async () => {
    renderDrawer({ ...withVin, identifier_type: 'serial', identifier: 'SN-9', has_vin: false } as Vehicle)
    expect(vinOption().disabled).toBe(false)
    fireEvent.change(typeSelect(), { target: { value: 'vin' } })
    expect(screen.queryByLabelText('identifier.valueLabel')).not.toBeInTheDocument()
    save()
    await waitFor(() => expect(mockedUpdate).toHaveBeenCalledTimes(1))
    expect(mockedUpdate).toHaveBeenCalledWith(withVin.vin, { identifier_type: 'vin' })
  })

  it('switching a VIN vehicle to a serial needs the serial, then sends both', async () => {
    renderDrawer(withVin)
    fireEvent.change(typeSelect(), { target: { value: 'serial' } })
    save()
    expect(await screen.findByText('identifier.required')).toBeInTheDocument()
    expect(mockedUpdate).not.toHaveBeenCalled()

    fireEvent.change(screen.getByLabelText('identifier.valueLabel'), { target: { value: ' SN-9 ' } })
    save()
    await waitFor(() => expect(mockedUpdate).toHaveBeenCalledTimes(1))
    expect(mockedUpdate).toHaveBeenCalledWith(withVin.vin, { identifier_type: 'serial', identifier: 'SN-9' })
  })

  it('sends only the identifier when only it changed', async () => {
    renderDrawer(qKeyed)
    fireEvent.change(screen.getByLabelText('identifier.valueLabel'), { target: { value: 'KBT-2' } })
    save()
    await waitFor(() => expect(mockedUpdate).toHaveBeenCalledTimes(1))
    expect(mockedUpdate).toHaveBeenCalledWith(qKeyed.vin, { identifier: 'KBT-2' })
  })

  it('switching to none hides the identifier and sends only the type', async () => {
    renderDrawer(qKeyed)
    fireEvent.change(typeSelect(), { target: { value: 'none' } })
    expect(screen.queryByLabelText('identifier.valueLabel')).not.toBeInTheDocument()
    save()
    await waitFor(() => expect(mockedUpdate).toHaveBeenCalledTimes(1))
    expect(mockedUpdate).toHaveBeenCalledWith(qKeyed.vin, { identifier_type: 'none' })
  })

  it("surfaces the server's 422 detail", async () => {
    const detail = "This vehicle was added without a VIN, so it can't be switched to one"
    mockedUpdate.mockRejectedValueOnce({
      isAxiosError: true,
      message: 'Request failed',
      response: { status: 422, data: { detail } },
    })
    const { onClose } = renderDrawer(qKeyed)
    fireEvent.change(screen.getByLabelText('identifier.valueLabel'), { target: { value: 'KBT-3' } })
    save()
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith(detail))
    expect(onClose).not.toHaveBeenCalled()
  })
})
