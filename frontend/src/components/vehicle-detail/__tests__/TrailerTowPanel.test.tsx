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

  it('clicking the tow vehicle link does not open the editor', async () => {
    getTrailerDetailsMock.mockResolvedValue({ tow_vehicle_vin: TOW_VEHICLE.vin })
    renderPanel(TRAILER)

    const link = await screen.findByRole('link', { name: 'Ram' })
    expect(link).toHaveAttribute('href', `/vehicles/${TOW_VEHICLE.vin}`)
    expect(screen.queryByText('detail.tow.notConnected')).not.toBeInTheDocument()

    // The link sits inside the click-to-edit card, so its click used to bubble
    // up and open the tow editor on the way out (#179). Asked by role, not by
    // text: the hidden edit button's text IS detail.tow.editTitle.
    fireEvent.click(link)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

    // And the rest of the card still edits, so the line above isn't passing
    // just because the card stopped opening anything.
    fireEvent.click(screen.getByText('detail.tow.hitch'))
    expect(await screen.findByRole('dialog')).toHaveAccessibleName('detail.tow.editTitle')
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
    // A tow vehicle's list is read-only (the pairing is edited from the
    // trailer's side), so this card isn't click-to-edit at all.
    expect(screen.queryByRole('button', { name: 'detail.tow.editTitle' })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: /KZ-Durango/ })).toBeInTheDocument()
  })

  // A type the app doesn't know reads as null. That's not a trailer, so the
  // panel shows the tow side: linked trailers, no pairing card.
  it('treats a null-type vehicle as motorized and lists its trailers', async () => {
    const unknown = { vin: '1FTFW1E50PFA00001', nickname: 'Mystery', vehicle_type: null } as Vehicle
    listTowedTrailersMock.mockResolvedValue([TRAILER])
    renderPanel(unknown)

    expect(await screen.findByText('detail.tow.linkedTrailers')).toBeInTheDocument()
    expect(listTowedTrailersMock).toHaveBeenCalledWith(unknown.vin)
    expect(getTrailerDetailsMock).not.toHaveBeenCalled()
    expect(screen.queryByText('detail.tow.title')).not.toBeInTheDocument()
  })

  // A null-type vehicle can still tow, so the trailer's picker offers it.
  // The second trailer is the control: trailers still drop out.
  it('offers a null-type vehicle as a tow candidate', async () => {
    const unknown = { vin: '1FTFW1E50PFA00001', nickname: 'Mystery', vehicle_type: null } as Vehicle
    const otherTrailer = { vin: '5SFBT2420LE000002', nickname: 'Utility', vehicle_type: 'Trailer' } as Vehicle
    listMock.mockResolvedValue({ vehicles: [TOW_VEHICLE, unknown, otherTrailer, TRAILER] })
    renderPanel(TRAILER)

    fireEvent.click(await screen.findByRole('button', { name: 'detail.tow.editTitle' }))
    const picker = within(await screen.findByRole('dialog')).getByLabelText('detail.tow.towVehicle')
    const offered = within(picker).getAllByRole('option').map((o) => (o as HTMLOptionElement).value)
    expect(offered).toEqual(['', TOW_VEHICLE.vin, unknown.vin])
  })
})
