/**
 * Service for VIN-related API calls
 */

import api from './api'
import type { VINDecodeResponse, VINValidationResponse } from '@/types/vin'

export const vinService = {
  /**
   * Validate a VIN format
   */
  async validate(vin: string): Promise<VINValidationResponse> {
    const response = await api.get<VINValidationResponse>(`/vin/validate/${vin}`)
    return response.data
  },

  /**
   * Decode a VIN using NHTSA API
   */
  async decode(vin: string): Promise<VINDecodeResponse> {
    const response = await api.post<VINDecodeResponse>('/vin/decode', { vin })
    return response.data
  },

  /**
   * Check whether a vehicle with this VIN already exists for the current user.
   * Returns true if a duplicate is detected. Surfaced by issue #69 — rc1's
   * duplicate-VIN error only fired at the end of the add-vehicle flow,
   * forcing users to redo the whole wizard. With this, the wizard can
   * warn on field blur and offer the user a chance to back out early.
   */
  async exists(vin: string): Promise<boolean> {
    try {
      await api.get(`/vehicles/${vin}`)
      return true
    } catch (err: unknown) {
      if (err && typeof err === 'object' && 'response' in err) {
        const status = (err as { response?: { status?: number } }).response?.status
        if (status === 404) return false
        // 403 means the vehicle exists but the user doesn't own it — still
        // a "duplicate" from the perspective of the add flow because the
        // backend's POST /vehicles will refuse to create another.
        if (status === 403) return true
      }
      // Network errors etc. — don't block the user. Fall through to the
      // existing end-of-flow duplicate guard.
      return false
    }
  },
}
