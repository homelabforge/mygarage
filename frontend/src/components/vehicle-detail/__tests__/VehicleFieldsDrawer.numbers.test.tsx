/**
 * Year, doors and cylinders are typed text checked by the edit form's own
 * rule (G1b-21). They were native number boxes whose min/max did nothing, so
 * a year of 1850 saved.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { render } from '../../../__tests__/test-utils'
import VehicleFieldsDrawer from '../VehicleFieldsDrawer'
import vehicleService from '../../../services/vehicleService'
import type { Vehicle } from '../../../types/vehicle'

vi.mock('../../../services/vehicleService', () => ({
  default: { update: vi.fn() },
}))

const mockedUpdate = vi.mocked(vehicleService).update
const VEHICLE = { vin: 'TEST0000000000001', year: 2019, make: 'Mitsubishi', model: 'Mirage', doors: 4 } as unknown as Vehicle

const renderDrawer = (card: 'basic' | 'details') =>
  render(
    <VehicleFieldsDrawer
      open
      onClose={vi.fn()}
      vehicle={VEHICLE}
      vin={VEHICLE.vin}
      card={card}
      onUpdated={vi.fn()}
    />,
  )

beforeEach(() => {
  vi.clearAllMocks()
  mockedUpdate.mockResolvedValue(VEHICLE)
})

describe('VehicleFieldsDrawer: whole-number fields', () => {
  it('refuses a year before 1900 and says so', async () => {
    renderDrawer('basic')
    fireEvent.change(screen.getByLabelText('edit.year'), { target: { value: '1850' } })
    fireEvent.click(screen.getByRole('button', { name: 'common:save' }))

    expect(await screen.findByText('common:validation.vehicle.yearTooEarly')).toBeInTheDocument()
    expect(mockedUpdate).not.toHaveBeenCalled()
    expect(screen.getByLabelText('edit.year')).toHaveAttribute('aria-invalid', 'true')
  })

  it('refuses half a door', async () => {
    renderDrawer('details')
    fireEvent.change(screen.getByLabelText('edit.doors'), { target: { value: '4.5' } })
    fireEvent.click(screen.getByRole('button', { name: 'common:save' }))

    expect(await screen.findByText('common:validation.vehicle.doorsNotWhole')).toBeInTheDocument()
    expect(mockedUpdate).not.toHaveBeenCalled()
  })

  it('saves a year in range as a number', async () => {
    renderDrawer('basic')
    fireEvent.change(screen.getByLabelText('edit.year'), { target: { value: '2021' } })
    fireEvent.click(screen.getByRole('button', { name: 'common:save' }))

    await waitFor(() => expect(mockedUpdate).toHaveBeenCalledWith(VEHICLE.vin, { year: 2021 }))
  })
})
