import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import type { Vehicle } from '../../../types/vehicle'

const listMock = vi.fn()
const getTrailerDetailsMock = vi.fn()
const listTowedTrailersMock = vi.fn()

vi.mock('../../../services/vehicleService', () => ({
  default: {
    list: (...a: unknown[]) => listMock(...a),
    getTrailerDetails: (...a: unknown[]) => getTrailerDetailsMock(...a),
    listTowedTrailers: (...a: unknown[]) => listTowedTrailersMock(...a),
    createTrailerDetails: vi.fn(),
    updateTrailerDetails: vi.fn(),
  },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import TrailerTowPanel from '../TrailerTowPanel'

const TOW_VEHICLE = { vin: '3C63R3PL1SG545506', nickname: 'Ram', vehicle_type: 'Truck' } as Vehicle
const TRAILER = { vin: '4EZFD3821P6080615', nickname: 'KZ-Durango', vehicle_type: 'FifthWheel' } as Vehicle

const renderPanel = (vehicle: Vehicle) =>
  render(
    <MemoryRouter>
      <TrailerTowPanel vehicle={vehicle} />
    </MemoryRouter>
  )

beforeEach(() => {
  vi.clearAllMocks()
  listMock.mockResolvedValue({ vehicles: [TOW_VEHICLE] })
  listTowedTrailersMock.mockResolvedValue([])
  getTrailerDetailsMock.mockResolvedValue({})
})

describe('TrailerTowPanel', () => {
  it('says the vehicle type is not connected when no tow vehicle is paired', async () => {
    getTrailerDetailsMock.mockResolvedValue({ tow_vehicle_vin: null })
    renderPanel(TRAILER)

    // The copy names the type rather than saying a bare "None", so the card
    // reads as a sentence like the other Overview cards.
    expect(await screen.findByText('detail.tow.notConnected')).toBeInTheDocument()
  })

  it('shows the paired vehicle as a link, above the card edit overlay', async () => {
    getTrailerDetailsMock.mockResolvedValue({ tow_vehicle_vin: TOW_VEHICLE.vin })
    renderPanel(TRAILER)

    const link = await screen.findByRole('link', { name: 'Ram' })
    expect(link).toHaveAttribute('href', `/vehicles/${TOW_VEHICLE.vin}`)
    expect(screen.queryByText('detail.tow.notConnected')).not.toBeInTheDocument()

    // The overlay is absolute inset-0 z-10, so a link left underneath it would
    // render but never be clickable. Its wrapper must out-stack the overlay.
    expect(link.parentElement).toHaveClass('z-20')
    // Both affordances coexist: the link navigates, the rest of the card edits.
    expect(screen.getByRole('button', { name: 'detail.tow.editTitle' })).toBeInTheDocument()
  })

  it('keeps the form out of the card and opens it in a drawer on click', async () => {
    renderPanel(TRAILER)
    // Nothing editable is inline: the fields only exist once the drawer opens.
    await waitFor(() => expect(screen.getByText('detail.tow.title')).toBeInTheDocument())
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'detail.tow.editTitle' }))
    const drawer = await screen.findByRole('dialog')
    expect(drawer).toHaveAccessibleName('detail.tow.editTitle')
    expect(within(drawer).getByLabelText('detail.tow.towVehicle')).toBeInTheDocument()
  })

  it('renders the linked-trailers list on a tow vehicle with no edit overlay', async () => {
    listTowedTrailersMock.mockResolvedValue([TRAILER])
    renderPanel(TOW_VEHICLE)

    expect(await screen.findByText('detail.tow.linkedTrailers')).toBeInTheDocument()
    // This card contains links, so it must NOT get the click-to-edit overlay:
    // the overlay sits above everything and would swallow them.
    expect(screen.queryByRole('button', { name: 'detail.tow.editTitle' })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: /KZ-Durango/ })).toBeInTheDocument()
  })
})
