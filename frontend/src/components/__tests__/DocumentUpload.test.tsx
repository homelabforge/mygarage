import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '../../__tests__/test-utils'
import userEvent from '@testing-library/user-event'

const uploadMock = vi.fn().mockResolvedValue({})
vi.mock('../../hooks/queries/useDocuments', () => ({
  useUploadDocument: () => ({ mutateAsync: uploadMock }),
}))

import DocumentUpload from '../DocumentUpload'

beforeEach(() => vi.clearAllMocks())

// The hidden <input type=file> is reachable THROUGH the sr-only <label htmlFor> the restyle adds;
// getByLabelText resolves it via that label, so a dropped/unassociated htmlFor fails the test.
const fileInput = () => screen.getByLabelText('documentUpload.misc.selectFile') as HTMLInputElement

describe('DocumentUpload — centered upload modal: guard + upload', () => {
  it('rejects an unsupported extension via the real labelled input: shows the invalid-type error, keeps the no-file view (the invalid file is NOT retained), leaves Upload DISABLED, and never calls the mutation even when Upload is clicked (fails if the ext guard is dropped, the input is unassociated, the invalid file is retained, or the guard leaves a submittable invalid state)', async () => {
    // applyAccept:false so the component's OWN validExtensions guard — not userEvent's accept
    // filter — rejects the .exe (userEvent 14.6.1 .upload() takes NO per-call options arg).
    const user = userEvent.setup({ applyAccept: false })
    render(<DocumentUpload vin="V1" onSuccess={vi.fn()} onClose={vi.fn()} />)
    await user.upload(fileInput(), new File(['x'], 'malware.exe', { type: 'application/octet-stream' }))
    expect(screen.getByText('documentUpload.misc.invalidFileType')).toBeInTheDocument()
    // R2-M2/M3: DocumentUpload disables Upload with `!file || !title`, so a disabled-Upload
    // assertion ALONE does NOT prove `file` stayed unset (an empty title disables it regardless —
    // a broken guard could `setFile(bad)` yet still show disabled). PROVE the invalid file was not
    // retained: the no-file dropzone view remains — the Choose-File <Button> renders ONLY under the
    // `!file` branch, so its presence proves `file` is still unset.
    expect(screen.getByRole('button', { name: 'documentUpload.misc.selectFile' })).toBeInTheDocument()
    // Then also: mutateAsync only runs from handleSubmit, so prove no submittable invalid state —
    // Upload is disabled (`disabled={uploading || !file || !title}`) and clicking calls nothing.
    const upload = screen.getByRole('button', { name: 'documentUpload.uploadBtn' })
    expect(upload).toBeDisabled()
    await user.click(upload)
    expect(uploadMock).not.toHaveBeenCalled()
  })

  it('uploads a PDF via the labelled input (title auto-filled from the file name), then Upload calls mutateAsync with the EXACT FormData fields + fires onSuccess/onClose (fails if the input is unassociated, the file/title is dropped/mis-fielded, or an empty field leaks in)', async () => {
    const user = userEvent.setup({ applyAccept: false })
    const onSuccess = vi.fn(); const onClose = vi.fn()
    render(<DocumentUpload vin="V1" onSuccess={onSuccess} onClose={onClose} />)
    const input = fileInput()
    const file = new File(['%PDF-1.4'], 'policy.pdf', { type: 'application/pdf' })
    await user.upload(input, file)          // handleFile sets file + auto-title 'policy'
    await user.click(screen.getByRole('button', { name: 'documentUpload.uploadBtn' }))
    await vi.waitFor(() => expect(uploadMock).toHaveBeenCalledTimes(1))
    const body = uploadMock.mock.calls[0][0] as FormData
    expect(body).toBeInstanceOf(FormData)
    expect(body.get('file')).toBe(file)              // the exact File under 'file'
    expect(body.get('title')).toBe('policy')         // auto-filled from the file name (extension stripped)
    expect(body.get('document_type')).toBeNull()     // untouched select ('') is NOT appended
    expect(body.get('description')).toBeNull()        // empty description is NOT appended
    // M4: the EXACT field-name set — an extra FormData key fails this. Default state = file + title.
    expect(Array.from(body.keys()).sort()).toStrictEqual(['file', 'title'])
    await vi.waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('a populated upload calls mutateAsync with document_type + the EXACT typed description + the auto title + no extra fields (fails if a populated field is dropped, mis-fielded, or an empty field leaks in)', async () => {
    const user = userEvent.setup({ applyAccept: false })
    render(<DocumentUpload vin="V1" onSuccess={vi.fn()} onClose={vi.fn()} />)
    const file = new File(['%PDF-1.4'], 'policy.pdf', { type: 'application/pdf' })
    await user.upload(fileInput(), file)                                  // handleFile sets file (sync) + auto-title 'policy'
    await user.selectOptions(await screen.findByLabelText('documentUpload.misc.documentTypeLabel'), 'Insurance')
    await user.type(screen.getByLabelText('documentList.descriptionLabel'), 'Full coverage policy')
    await user.click(screen.getByRole('button', { name: 'documentUpload.uploadBtn' }))
    await vi.waitFor(() => expect(uploadMock).toHaveBeenCalledTimes(1))
    const body = uploadMock.mock.calls[0][0] as FormData
    expect(body.get('title')).toBe('policy')                    // the auto title survives
    expect(body.get('document_type')).toBe('Insurance')         // the selected type
    expect(body.get('description')).toBe('Full coverage policy') // the EXACT typed description
    expect(Array.from(body.keys()).sort()).toStrictEqual(['description', 'document_type', 'file', 'title'])
  })

  it('the Choose-File button opens the file picker via the input ref (fails if the Button is unwired)', async () => {
    // M5: DocumentUpload's sr-only <label> text AND the Choose-File Button text are both
    // 'documentUpload.misc.selectFile' — getByLabelText resolves the input, getByRole('button', …)
    // the Button, no collision. Activating the Button proves its onClick → fileInputRef.current.click().
    const user = userEvent.setup()
    render(<DocumentUpload vin="V1" onSuccess={vi.fn()} onClose={vi.fn()} />)
    const input = screen.getByLabelText('documentUpload.misc.selectFile') as HTMLInputElement
    const clickSpy = vi.spyOn(input, 'click')
    const chooseBtn = screen.getByRole('button', { name: 'documentUpload.misc.selectFile' })
    chooseBtn.focus()
    await user.keyboard('{Enter}')
    expect(clickSpy).toHaveBeenCalledTimes(1)
  })

  it('the close X is an IconButton with an accessible name and fires onClose (fails if the close control loses its accessible name or wiring)', () => {
    const onClose = vi.fn()
    render(<DocumentUpload vin="V1" onSuccess={vi.fn()} onClose={onClose} />)
    const close = screen.getByRole('button', { name: 'common:close' })
    expect(close).toHaveAttribute('aria-label', 'common:close')
    close.click()
    expect(onClose).toHaveBeenCalled()
  })

  // Final-review I4 regression fence: `file` has no fieldErrors-wired Field
  // (only title/document_type/description do), so a 422 naming it used to
  // write to fieldErrors state, render nothing, and — under the old
  // `problems.length > 0 ? fieldErrors : setError(...)` gate — suppress the
  // banner too. applyControlledFieldErrors's attached/unhandled split must
  // still surface the banner when nothing attached.
  it('a 422 naming ONLY file (no render target) shows the banner, not silence', async () => {
    const user = userEvent.setup({ applyAccept: false })
    uploadMock.mockRejectedValueOnce({
      isAxiosError: true,
      message: 'Request failed with status code 422',
      response: {
        status: 422,
        data: { detail: [{ type: 'value_error', loc: ['body', 'file'], msg: 'Unsupported file content' }] },
      },
    })
    render(<DocumentUpload vin="V1" onSuccess={vi.fn()} onClose={vi.fn()} />)
    const file = new File(['%PDF-1.4'], 'policy.pdf', { type: 'application/pdf' })
    await user.upload(fileInput(), file)
    await user.click(screen.getByRole('button', { name: 'documentUpload.uploadBtn' }))
    await vi.waitFor(() => expect(uploadMock).toHaveBeenCalledTimes(1))
    expect(
      await screen.findByText('Failed to documentUpload.uploadAction. Please check your input.')
    ).toBeInTheDocument()
  })
})
