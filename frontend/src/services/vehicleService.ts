/**
 * Vehicle API service
 */

import api from './api'
import type {
  Vehicle,
  VehicleCreate,
  VehicleUpdate,
  VehicleListResponse,
  VehiclePhotoListResponse,
  VehiclePhotoUploadResponse,
  TrailerDetails,
  TrailerDetailsCreate,
  TrailerDetailsUpdate,
} from '../types/vehicle'
import type { PhotoUpdate } from '../types/photo'

/**
 * Vehicle CRUD operations
 */

export const vehicleService = {
  /**
   * Get all vehicles
   */
  async list(skip = 0, limit = 100): Promise<VehicleListResponse> {
    const response = await api.get<VehicleListResponse>('/vehicles', {
      params: { skip, limit },
    })
    return response.data
  },

  /**
   * Get a single vehicle by VIN
   */
  async get(vin: string): Promise<Vehicle> {
    const response = await api.get<Vehicle>(`/vehicles/${vin}`)
    return response.data
  },

  /**
   * Create a new vehicle
   */
  async create(vehicle: VehicleCreate): Promise<Vehicle> {
    const response = await api.post<Vehicle>('/vehicles', vehicle)
    return response.data
  },

  /**
   * Update an existing vehicle
   */
  async update(vin: string, vehicle: VehicleUpdate): Promise<Vehicle> {
    const response = await api.put<Vehicle>(`/vehicles/${vin}`, vehicle)
    return response.data
  },

  /**
   * Delete a vehicle
   */
  async delete(vin: string): Promise<void> {
    await api.delete(`/vehicles/${vin}`)
  },

  /**
   * Photo operations
   */

  /**
   * Upload a photo for a vehicle
   */
  async uploadPhoto(vin: string, file: File): Promise<VehiclePhotoUploadResponse> {
    const formData = new FormData()
    formData.append('file', file)

    const response = await api.post<VehiclePhotoUploadResponse>(
      `/vehicles/${vin}/photos`,
      formData,
      {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      }
    )
    return response.data
  },

  /**
   * List all photos for a vehicle
   */
  async listPhotos(vin: string): Promise<VehiclePhotoListResponse> {
    const response = await api.get<VehiclePhotoListResponse>(`/vehicles/${vin}/photos`)
    return response.data
  },

  /**
   * Get photo URL
   */
  getPhotoUrl(vin: string, filename: string): string {
    return `/api/vehicles/${vin}/photos/${filename}`
  },

  /**
   * Delete a photo
   */
  async deletePhoto(vin: string, filename: string): Promise<void> {
    await api.delete(`/vehicles/${vin}/photos/${filename}`)
  },

  /**
   * Update caption or metadata for a photo
   */
  async updatePhoto(vin: string, photoId: number, payload: PhotoUpdate): Promise<void> {
    await api.patch(`/vehicles/${vin}/photos/${photoId}`, payload)
  },

  /**
   * Set main photo for a vehicle
   */
  async setMainPhoto(vin: string, filename: string): Promise<Vehicle> {
    const response = await api.put<Vehicle>(`/vehicles/${vin}/main-photo`, null, {
      params: { filename },
    })
    return response.data
  },

  /**
   * Trailer details operations
   */

  /**
   * Get trailer details for a vehicle
   */
  async getTrailerDetails(vin: string): Promise<TrailerDetails> {
    const response = await api.get<TrailerDetails>(`/vehicles/${vin}/trailer`)
    return response.data
  },

  /**
   * Create trailer details for a vehicle
   */
  async createTrailerDetails(vin: string, details: TrailerDetailsCreate): Promise<TrailerDetails> {
    const response = await api.post<TrailerDetails>(`/vehicles/${vin}/trailer`, details)
    return response.data
  },

  /**
   * Update trailer details for a vehicle
   */
  async updateTrailerDetails(vin: string, details: TrailerDetailsUpdate): Promise<TrailerDetails> {
    const response = await api.put<TrailerDetails>(`/vehicles/${vin}/trailer`, details)
    return response.data
  },
}

export default vehicleService
