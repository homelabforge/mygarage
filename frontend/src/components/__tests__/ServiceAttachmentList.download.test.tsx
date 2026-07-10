import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '../../__tests__/test-utils'
import ServiceAttachmentList from '../ServiceAttachmentList'
import type { Attachment } from '../../types/attachment'

const attachment: Attachment = {
  id: 1,
  file_name: 'receipt.pdf',
  file_size: 1234,
  file_type: 'application/pdf',
  download_url: '/api/attachments/1/download',
  record_id: 5,
  record_type: 'service',
  uploaded_at: '2025-01-06T12:00:00',
} as Attachment

const apiGet = vi.fn()

vi.mock('../../services/api', () => ({
  default: {
    get: (...args: unknown[]) => apiGet(...args),
  },
}))

// URL.createObjectURL is not implemented in jsdom
beforeEach(() => {
  apiGet.mockReset()
  apiGet.mockImplementation((url: string) => {
    if (url.endsWith('/attachments')) {
      return Promise.resolve({ data: { attachments: [attachment] } })
    }
    return Promise.resolve({ data: new Blob() })
  })
  window.URL.createObjectURL = vi.fn(() => 'blob:mock')
  window.URL.revokeObjectURL = vi.fn()
})

describe('ServiceAttachmentList download (baseURL-relative axios arg)', () => {
  it('calls api.get with the /api-stripped path, not the raw download_url', async () => {
    render(<ServiceAttachmentList recordId={5} />)

    const downloadButton = await screen.findByRole('button', { name: /download/i })
    fireEvent.click(downloadButton)

    await waitFor(() => {
      expect(apiGet).toHaveBeenLastCalledWith('/attachments/1/download', expect.objectContaining({ responseType: 'blob' }))
    })
  })
})
