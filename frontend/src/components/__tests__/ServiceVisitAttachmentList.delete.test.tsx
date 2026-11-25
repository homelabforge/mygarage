import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '../../__tests__/test-utils'
import ServiceVisitAttachmentList from '../ServiceVisitAttachmentList'
import type { Attachment } from '../../types/attachment'
import { answerConfirm } from '../../__tests__/confirmHelpers'

// Delete asks through the app confirm first; only a yes reaches the API.

const attachment: Attachment = {
  id: 1,
  file_name: 'receipt.pdf',
  file_size: 1234,
  file_type: 'application/pdf',
  download_url: '/api/attachments/1/download',
  record_id: 5,
  record_type: 'service_visit',
  uploaded_at: '2025-01-06T12:00:00',
} as Attachment

const apiGet = vi.fn()
const apiDelete = vi.fn()

vi.mock('../../services/api', () => ({
  default: {
    get: (...args: unknown[]) => apiGet(...args),
    delete: (...args: unknown[]) => apiDelete(...args),
  },
}))

beforeEach(() => {
  apiGet.mockReset()
  apiDelete.mockReset()
  apiGet.mockResolvedValue({ data: { attachments: [attachment] } })
  apiDelete.mockResolvedValue({ data: {} })
})

describe('ServiceVisitAttachmentList delete', () => {
  it('a confirmed delete deletes that attachment', async () => {
    render(<ServiceVisitAttachmentList visitId={5} />)
    fireEvent.click(await screen.findByRole('button', { name: 'common:delete' }))
    await answerConfirm('confirm', 'serviceVisitAttachments.confirmDelete')
    await waitFor(() => expect(apiDelete).toHaveBeenCalledWith('/attachments/1'))
  })

  it('a cancelled delete deletes nothing', async () => {
    render(<ServiceVisitAttachmentList visitId={5} />)
    fireEvent.click(await screen.findByRole('button', { name: 'common:delete' }))
    await answerConfirm('cancel', 'serviceVisitAttachments.confirmDelete')
    expect(apiDelete).not.toHaveBeenCalled()
  })
})
