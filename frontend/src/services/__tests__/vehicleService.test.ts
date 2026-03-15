import { describe, it, expect, vi, beforeEach } from 'vitest'
import vehicleService from '../vehicleService'
import api from '../api'

vi.mock('../api', () => ({
  default: {
    put: vi.fn(),
  },
}))

describe('vehicleService.setMainPhoto', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('calls PUT /vehicles/{vin}/photos/main with filename query param', async () => {
    const mockVehicle = { vin: 'TEST123', make: 'Honda', model: 'Civic' }
    vi.mocked(api.put).mockResolvedValue({ data: mockVehicle })

    await vehicleService.setMainPhoto('TEST123', 'photo1.jpg')

    expect(api.put).toHaveBeenCalledWith(
      '/vehicles/TEST123/photos/main',
      null,
      { params: { filename: 'photo1.jpg' } }
    )
  })

  it('returns the vehicle response', async () => {
    const mockVehicle = { vin: 'TEST123', main_photo: 'photo1.jpg' }
    vi.mocked(api.put).mockResolvedValue({ data: mockVehicle })

    const result = await vehicleService.setMainPhoto('TEST123', 'photo1.jpg')

    expect(result).toEqual(mockVehicle)
  })
})
