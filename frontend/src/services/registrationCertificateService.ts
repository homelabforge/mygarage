/**
 * The registration certificate import (#211): read a carte grise (or any EU
 * certificate) before a vehicle exists, or store and apply it on one.
 */

import api from './api'
import type { components } from '@/types/api.generated'

export type RegistrationParseResponse = components['schemas']['RegistrationParseResponse']
export type RegistrationImportResponse = components['schemas']['RegistrationImportResponse']
export type SuggestedTaxRecord = components['schemas']['SuggestedTaxRecord']

/** The 409 code the reader answers with when a photo needs a vision model nobody configured. */
export const AI_READING_NOT_CONFIGURED = 'ai_reading_not_configured'

export const CERTIFICATE_ACCEPT = 'application/pdf,image/jpeg,image/png,image/heic,image/heif'
export const CERTIFICATE_MIME_TYPES = ['application/pdf', 'image/jpeg', 'image/png', 'image/heic', 'image/heif']
export const CERTIFICATE_MAX_BYTES = 25 * 1024 * 1024

/** Duck-typed on the response, like `httpErrorHandler`: no axios class check. */
export function isAiNotConfigured(error: unknown): boolean {
  if (!error || typeof error !== 'object' || !('response' in error)) return false
  const response = (error as { response?: { status?: number; data?: { detail?: unknown } } }).response
  return response?.status === 409 && response.data?.detail === AI_READING_NOT_CONFIGURED
}

/** A PDF is read from its own text when it has one; a photo needs the vision model. */
export function isPdf(file: File): boolean {
  return file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')
}

export const registrationCertificateService = {
  /** Read a certificate and get what it would fill. Writes nothing. */
  async parse(file: File, country?: string | null): Promise<RegistrationParseResponse> {
    const form = new FormData()
    form.append('file', file)
    const response = await api.post<RegistrationParseResponse>('/registration-certificate/parse', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      params: country ? { country } : undefined,
    })
    return response.data
  },

  /** Store the certificate on the vehicle, fill its empty fields, record X.1. */
  async importForVehicle(vin: string, file: File, overwrite = false): Promise<RegistrationImportResponse> {
    const form = new FormData()
    form.append('file', file)
    const response = await api.post<RegistrationImportResponse>(
      `/vehicles/${vin}/registration-certificate`,
      form,
      {
        headers: { 'Content-Type': 'multipart/form-data' },
        params: overwrite ? { overwrite: true } : undefined,
      }
    )
    return response.data
  },

  /** The tax records the person ticked on the wizard's review step. */
  async createTaxRecords(vin: string, records: SuggestedTaxRecord[]): Promise<void> {
    for (const record of records) {
      await api.post(`/vehicles/${vin}/tax-records`, {
        vin,
        date: record.date,
        tax_type: record.tax_type,
        amount: record.amount,
        notes: `Registration certificate, field ${record.code}`,
      })
    }
  },
}

export default registrationCertificateService
