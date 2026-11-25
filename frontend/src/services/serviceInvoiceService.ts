/**
 * Read a workshop invoice, job card or quote into a draft service visit.
 * The server writes nothing; the form fills from the draft.
 */

import api from './api'
import type { components } from '@/types/api.generated'

export type ServiceInvoiceReadResponse = components['schemas']['ServiceInvoiceReadResponse']
export type ServiceInvoiceDraft = components['schemas']['ServiceInvoiceDraft']
export type ServiceInvoiceDraftLine = components['schemas']['ServiceInvoiceDraftLine']

export const INVOICE_ACCEPT = 'application/pdf,image/jpeg,image/png,image/heic,image/heif,image/webp'

export const serviceInvoiceService = {
  async read(vin: string, file: File, allowExternalVision = false): Promise<ServiceInvoiceReadResponse> {
    const form = new FormData()
    form.append('file', file)
    const response = await api.post<ServiceInvoiceReadResponse>(
      `/vehicles/${vin}/service-visits/read-invoice`,
      form,
      {
        headers: { 'Content-Type': 'multipart/form-data' },
        params: allowExternalVision ? { allow_external_vision: true } : undefined,
        // A long invoice on a local model takes minutes, not the default timeout.
        timeout: 330_000,
      },
    )
    return response.data
  },
}

export default serviceInvoiceService
