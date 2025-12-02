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
}
