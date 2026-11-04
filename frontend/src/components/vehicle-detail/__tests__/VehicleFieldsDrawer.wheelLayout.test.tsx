import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, fireEvent, waitFor } from '@testing-library/react'
import { render } from '../../../__tests__/test-utils'
import VehicleFieldsDrawer from '../VehicleFieldsDrawer'
import vehicleService from '../../../services/vehicleService'
import type { Vehicle } from '../../../types/vehicle'

// Real English, so the Automatic option shows the layout it would pick.
vi.mock('react-i18next', async () => (await import('@/__tests__/i18nEn')).reactI18nextEn())
vi.mock('../../../services/vehicleService', () => ({
  default: { update: vi.fn() },
}))

const mockedUpdate = vi.mocked(vehicleService).update

// The wheel layout on the Vehicle Details sidecar (#272).
const motorcycle = {
  vin: 'TEST0000000000272',
  nickname: 'Bike',
  vehicle_type: 'Motorcycle',
  year: 2021,
  wheel_layout: null,
  effective_wheel_layout: 'two',
  default_wheel_layout: 'two',
} as unknown as Vehicle

const truck = {
  ...motorcycle,
  vehicle_type: 'Truck',
  wheel_layout: 'dually',
  effective_wheel_layout: 'dually',
  default_wheel_layout: 'four',
} as unknown as Vehicle

function renderDrawer(vehicle: Vehicle): { onClose: ReturnType<typeof vi.fn> } {
  const onClose = vi.fn()
  render(
    <VehicleFieldsDrawer
      open
      onClose={onClose}
      vehicle={vehicle}
      vin={vehicle.vin}
      card="details"
      onUpdated={vi.fn()}
    />,
  )
  return { onClose }
}

const layoutSelect = (): HTMLSelectElement => screen.getByLabelText('Wheel layout') as HTMLSelectElement
const save = (): void => {
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))
}

describe('VehicleFieldsDrawer wheel layout', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedUpdate.mockResolvedValue(motorcycle)
  })

  it('names the automatic layout, then offers all six, for any vehicle type', () => {
    renderDrawer(motorcycle)
    const options = Array.from(layoutSelect().options).map((o) => [o.value, o.textContent])
    expect(options).toEqual([
      ['', 'Automatic: Two wheels (front and rear)'],
      ['four', 'Four wheels'],
      ['two', 'Two wheels (front and rear)'],
      ['trike_2f1r', 'Trike, two front wheels'],
      ['trike_1f2r', 'Trike, two rear wheels'],
      ['dually', 'Dual rear wheels (dually)'],
      ['none', 'No wheels'],
    ])
    expect(layoutSelect()).toHaveValue('')
  })

  it('choosing dually sends only the layout', async () => {
    renderDrawer(motorcycle)
    fireEvent.change(layoutSelect(), { target: { value: 'dually' } })
    save()
    await waitFor(() => expect(mockedUpdate).toHaveBeenCalledTimes(1))
    expect(mockedUpdate.mock.calls[0][1]).toStrictEqual({ wheel_layout: 'dually' })
  })

  it('choosing Automatic on an override sends null', async () => {
    renderDrawer(truck)
    expect(layoutSelect()).toHaveValue('dually')
    fireEvent.change(layoutSelect(), { target: { value: '' } })
    save()
    await waitFor(() => expect(mockedUpdate).toHaveBeenCalledTimes(1))
    expect(mockedUpdate.mock.calls[0][1]).toStrictEqual({ wheel_layout: null })
  })

  it.each([
    ['automatic', motorcycle],
    ['an override', truck],
  ])('saving %s with no change sends nothing', (_label, vehicle) => {
    const { onClose } = renderDrawer(vehicle)
    // Present, so the no-PUT below isn't just a missing field.
    expect(layoutSelect()).toBeInTheDocument()
    save()
    expect(mockedUpdate).not.toHaveBeenCalled()
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})
