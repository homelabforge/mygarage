/**
 * Service for VIN-related API calls
 */

import api from './api'
import type {
  AutoRefCandidate,
  AutoRefTestResponse,
  VINDecodeResponse,
  VINProvider,
  VINProvidersResponse,
  VINValidationResponse,
} from '@/types/vin'

export interface VINDecodeOptions {
  /** Only after the person chose one; omitted is Automatic, with fallback. */
  provider?: VINProvider
  /** The country that orders the decoders (ISO 3166-1 alpha-2). */
  country?: string | null
}

export const vinService = {
  /**
   * Validate a VIN format
   */
  async validate(vin: string): Promise<VINValidationResponse> {
    const response = await api.get<VINValidationResponse>(`/vin/validate/${vin}`)
    return response.data
  },

  /**
   * Decode a VIN. Without a provider the backend asks the preferred decoder
   * first and falls back to NHTSA; a provider runs alone (#219).
   */
  async decode(vin: string, options: VINDecodeOptions = {}): Promise<VINDecodeResponse> {
    const body: { vin: string; provider?: VINProvider; country?: string } = { vin }
    if (options.provider) body.provider = options.provider
    if (options.country) body.country = options.country
    const response = await api.post<VINDecodeResponse>('/vin/decode', body)
    return response.data
  },

  /**
   * Decode the version picked from an AutoRef decode's candidates (1 AutoRef
   * request). Its model and power go back so the backend can check AutoRef
   * still has that version under that id.
   */
  async decodeVersion(vin: string, candidate: AutoRefCandidate): Promise<VINDecodeResponse> {
    const response = await api.post<VINDecodeResponse>('/vin/autoref/version', {
      vin,
      record_type: candidate.record_type,
      id: candidate.id,
      gearbox_code: candidate.gearbox_code,
      expect_model: candidate.model_full,
      expect_kw: candidate.kw,
      grouped: candidate.grouped,
    })
    return response.data
  },

  /** The decoders this instance can use and which one Automatic asks first. */
  async providers(country?: string | null): Promise<VINProvidersResponse> {
    const response = await api.get<VINProvidersResponse>('/vin/providers', {
      params: country ? { country } : {},
    })
    return response.data
  },

  /** Check an AutoRef key (admin). Null or the mask tests the stored one; costs no quota. */
  async testAutoRef(apiKey: string | null): Promise<AutoRefTestResponse> {
    const response = await api.post<AutoRefTestResponse>('/vin/autoref/test', { api_key: apiKey })
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
