import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '../../__tests__/test-utils'
import { fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import api from '../../services/api'
import type { Document } from '../../types/document'

const useDocumentsMock = vi.fn()
const deleteMutate = vi.fn()
vi.mock('../../hooks/queries/useDocuments', () => ({
  useDocuments: () => useDocumentsMock(),
  useDeleteDocument: () => ({ mutate: deleteMutate, isPending: false, variables: undefined }),
}))
vi.mock('../../services/api', () => ({ default: { get: vi.fn(), put: vi.fn() } }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const apiGet = api.get as unknown as ReturnType<typeof vi.fn>
const apiPut = api.put as unknown as ReturnType<typeof vi.fn>

import DocumentList from '../DocumentList'
import { answerConfirm } from '../../__tests__/confirmHelpers'

const doc = {
  id: 5, title: 'Insurance Policy', document_type: 'Insurance', description: 'Full coverage',
  file_name: 'policy.pdf', file_size: 1536, mime_type: 'application/pdf', uploaded_at: '2026-01-01T12:00:00',
} as unknown as Document

const onAddClick = vi.fn()
const PROPS = { vin: 'V1', onAddClick }

beforeEach(() => {
  vi.clearAllMocks()
  Object.defineProperty(window.URL, 'createObjectURL', { value: vi.fn(() => 'blob:x'), writable: true, configurable: true })
  Object.defineProperty(window.URL, 'revokeObjectURL', { value: vi.fn(), writable: true, configurable: true })
  // jsdom cannot navigate to the blob: URL a download anchor points at, and
  // logs "Not implemented: navigation to another Document" on every click.
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
  useDocumentsMock.mockReturnValue({ data: { documents: [doc] }, isLoading: false, error: null })
})

describe('DocumentList — rendering + row actions', () => {
  it('renders the title, file name, type chip, and the formatted file size (fails if a field is dropped or the size renders raw bytes)', () => {
    render(<DocumentList {...PROPS} />)
    expect(screen.getByText('Insurance Policy')).toBeInTheDocument()
    expect(screen.getByText('policy.pdf')).toBeInTheDocument()
    expect(screen.getByText('Insurance')).toBeInTheDocument()      // the document_type <Chip>
    expect(screen.getByText('1.5 KB')).toBeInTheDocument()         // formatFileSize(1536) — NOT '1536'
  })

  it('clicking Download calls api.get with the download URL + blob responseType (fails if download is unwired or the URL changes)', async () => {
    apiGet.mockResolvedValue({ data: new Blob(['x']) })
    render(<DocumentList {...PROPS} />)
    fireEvent.click(screen.getByRole('button', { name: 'documentList.download' }))
    await waitFor(() =>
      expect(apiGet).toHaveBeenCalledWith('/vehicles/V1/documents/5/download', { responseType: 'blob' }),
    )
  })

  it('clicking Delete (confirm accepted) calls the delete mutation with the document id (fails if delete is unwired or the confirm gate is dropped)', async () => {
    render(<DocumentList {...PROPS} />)
    fireEvent.click(screen.getByRole('button', { name: 'common:delete' }))
    await answerConfirm('confirm', 'documentList.confirmDelete')
    expect(deleteMutate).toHaveBeenCalledWith(5, expect.anything())
  })

  it('clicking Delete with confirm REJECTED does NOT call the mutation (fails if the confirm gate is bypassed)', async () => {
    render(<DocumentList {...PROPS} />)
    fireEvent.click(screen.getByRole('button', { name: 'common:delete' }))
    await answerConfirm('cancel', 'documentList.confirmDelete')
    expect(deleteMutate).not.toHaveBeenCalled()
  })

  it('editing a document PUTs the EXACT editData to the document endpoint (fails if edit is unwired, misfields the payload, or drops a field)', async () => {
    apiPut.mockResolvedValue({ data: {} })
    const user = userEvent.setup()
    render(<DocumentList {...PROPS} />)
    fireEvent.click(screen.getByRole('button', { name: 'common:edit' }))
    const titleInput = screen.getByDisplayValue('Insurance Policy')
    await user.clear(titleInput)
    await user.type(titleInput, 'Updated Policy')
    fireEvent.click(screen.getByRole('button', { name: 'documentList.save' }))
    await waitFor(() => expect(apiPut).toHaveBeenCalledTimes(1))
    // M4/LD6: strict payload — a dropped/extra field or a wrong endpoint fails toStrictEqual
    // (honors the LD6 "never objectContaining" promise; toHaveBeenCalledWith is not strict).
    expect(apiPut.mock.calls[0]).toStrictEqual([
      '/vehicles/V1/documents/5',
      { title: 'Updated Policy', document_type: 'Insurance', description: 'Full coverage' },
    ])
  })

  it('the row Download/Edit/Delete expose a real aria-label (IconButton), not a bare title (fails if any regresses to a title-only <button>)', () => {
    render(<DocumentList {...PROPS} />)
    expect(screen.getByRole('button', { name: 'documentList.download' })).toHaveAttribute('aria-label', 'documentList.download')
    expect(screen.getByRole('button', { name: 'common:edit' })).toHaveAttribute('aria-label', 'common:edit')
    expect(screen.getByRole('button', { name: 'common:delete' })).toHaveAttribute('aria-label', 'common:delete')
  })
})

describe('DocumentList — empty state', () => {
  it('with zero documents, the empty-state CTA fires onAddClick (fails if the CTA is unwired or the empty title changes)', () => {
    useDocumentsMock.mockReturnValue({ data: { documents: [] }, isLoading: false, error: null })
    render(<DocumentList {...PROPS} />)
    expect(screen.getByText('documentList.noRecords')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'documentList.uploadFirstDocument' }))
    expect(onAddClick).toHaveBeenCalled()
  })
})

describe('DocumentList — uploaded timestamp', () => {
  it('renders the upload date from the wire-shaped datetime (fails with "Invalid Date" if it is fed to the date-only formatter)', () => {
    render(<DocumentList {...PROPS} />)
    expect(screen.getByText('Jan 1, 2026')).toBeInTheDocument()
    expect(screen.queryByText(/Invalid Date/)).toBeNull()
  })
})

describe('DocumentList: a document needs a title', () => {
  it('blanking the title shows an inline error and saves nothing', async () => {
    const user = userEvent.setup()
    render(<DocumentList {...PROPS} />)
    fireEvent.click(screen.getByRole('button', { name: 'common:edit' }))
    await user.clear(screen.getByDisplayValue('Insurance Policy'))
    await user.type(screen.getByLabelText('documentList.titleLabel *'), '   ')
    fireEvent.click(screen.getByRole('button', { name: 'documentList.save' }))
    expect(await screen.findByText('common:validation.document.titleRequired')).toBeInTheDocument()
    expect(apiPut).not.toHaveBeenCalled()
  })
})
