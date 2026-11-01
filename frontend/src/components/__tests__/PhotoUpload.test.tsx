import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '../../__tests__/test-utils'
import userEvent from '@testing-library/user-event'
import api from '../../services/api'

vi.mock('../../services/api', () => ({ default: { post: vi.fn() } }))
const postMock = api.post as unknown as ReturnType<typeof vi.fn>

import PhotoUpload from '../PhotoUpload'

beforeEach(() => vi.clearAllMocks())

// B3/M6: the hidden <input type=file> is reachable THROUGH the sr-only <label htmlFor> the
// restyle adds; getByLabelText resolves the input via that label, so a dropped/unassociated
// htmlFor fails the test — a querySelector could not. The sr-only label text is the static
// 'photoUpload.selectFile' (it does NOT flip to the file name — that shows in the dropzone <p>).
const fileInput = () => screen.getByLabelText('photoUpload.selectFile') as HTMLInputElement

describe('PhotoUpload — centered upload modal: guard + upload', () => {
  it('rejects a non-image via the real labelled input: shows the invalid-type error, leaves Upload DISABLED, and never calls the API even when Upload is clicked (fails if the type guard is dropped, the input is unassociated, or the guard leaves a submittable invalid state)', async () => {
    // applyAccept:false is a setup()-time Option (userEvent 14.6.1 .upload() takes NO per-call
    // options arg), so the component's OWN validTypes guard — not userEvent's accept filter —
    // rejects the .txt.
    const user = userEvent.setup({ applyAccept: false })
    render(<PhotoUpload vin="V1" onSuccess={vi.fn()} onClose={vi.fn()} />)
    await user.upload(fileInput(), new File(['x'], 'notes.txt', { type: 'text/plain' }))
    expect(screen.getByText('photoUpload.errorInvalidType')).toBeInTheDocument()
    // M3: the API only runs from handleSubmit, so "not called" is trivially true even for a broken
    // guard that shows the error yet RETAINS the bad file. Prove no submittable invalid state:
    // Upload is disabled (`disabled={uploading || !file}`) and clicking it still POSTs nothing.
    const upload = screen.getByRole('button', { name: 'photoUpload.uploadBtn' })
    expect(upload).toBeDisabled()
    await user.click(upload)
    expect(postMock).not.toHaveBeenCalled()
  })

  it('uploads an image via the labelled input, then Upload POSTs the EXACT File to the exact endpoint/options + fires onSuccess/onClose (fails if the input is unassociated, the file is dropped/mis-fielded, or the endpoint/options are wrong)', async () => {
    const user = userEvent.setup({ applyAccept: false })
    postMock.mockResolvedValue({ data: {} })
    const onSuccess = vi.fn(); const onClose = vi.fn()
    render(<PhotoUpload vin="1HGCM82633A004352" onSuccess={onSuccess} onClose={onClose} />)
    const input = fileInput()
    const file = new File(['ÿØÿ'], 'front.jpg', { type: 'image/jpeg' })
    await user.upload(input, file)
    expect(input.files?.[0]).toBe(file) // the visible label is wired to THIS input
    await user.click(screen.getByRole('button', { name: 'photoUpload.uploadBtn' }))
    await vi.waitFor(() => expect(postMock).toHaveBeenCalledTimes(1))
    // B4: assert object identity + field name + endpoint + the exact multipart options — NOT
    // merely toBeInstanceOf(File), which any substituted File would satisfy.
    const [url, body, opts] = postMock.mock.calls[0] as [string, FormData, Record<string, unknown>]
    expect(url).toBe('/vehicles/1HGCM82633A004352/photos')
    expect(body).toBeInstanceOf(FormData)
    expect(body.get('file')).toBe(file)         // the exact File under the exact field name 'file'
    expect(body.get('set_as_main')).toBe('false') // untouched checkbox default
    expect(body.get('caption')).toBeNull()        // empty caption is NOT appended
    // M4: the EXACT field-name set — an extra FormData key fails this (a sorted compare avoids
    // append-order fragility). Default state = exactly file + set_as_main.
    expect(Array.from(body.keys()).sort()).toStrictEqual(['file', 'set_as_main'])
    expect(opts).toStrictEqual({ headers: { 'Content-Type': 'multipart/form-data' } }) // strict: no extra props
    await vi.waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('a populated upload POSTs set_as_main="true" + the EXACT typed caption + no extra fields (fails if the checkbox/caption is dropped, mis-fielded, or set_as_main is hard-coded false)', async () => {
    const user = userEvent.setup({ applyAccept: false })
    postMock.mockResolvedValue({ data: {} })
    render(<PhotoUpload vin="V1" onSuccess={vi.fn()} onClose={vi.fn()} />)
    const file = new File(['ÿØÿ'], 'front.jpg', { type: 'image/jpeg' })
    await user.upload(fileInput(), file)                                     // FileReader.onload reveals the preview view (async)
    await user.click(await screen.findByLabelText('photoUpload.setAsMain'))   // await the async preview render, then the set-as-main <Checkbox>
    await user.type(screen.getByLabelText('photoUpload.captionLabel'), 'Front three-quarter')
    await user.click(screen.getByRole('button', { name: 'photoUpload.uploadBtn' }))
    await vi.waitFor(() => expect(postMock).toHaveBeenCalledTimes(1))
    const body = postMock.mock.calls[0][1] as FormData
    expect(body.get('set_as_main')).toBe('true')            // the checked box — NOT hard-coded 'false'
    expect(body.get('caption')).toBe('Front three-quarter') // the EXACT typed caption
    expect(Array.from(body.keys()).sort()).toStrictEqual(['caption', 'file', 'set_as_main'])
  })

  it('the Choose-File button opens the file picker via the input ref (fails if the Button is unwired)', async () => {
    // M5: both suites otherwise reach the input only through its label; this activates the VISIBLE
    // Choose-File <Button> so replacing its onClick with a no-op would be caught. In PhotoUpload the
    // sr-only <label> text and the Button text are BOTH 'photoUpload.selectFile' — getByLabelText
    // resolves the input (a label is not a button) and getByRole('button', …) resolves the Button.
    const user = userEvent.setup()
    render(<PhotoUpload vin="V1" onSuccess={vi.fn()} onClose={vi.fn()} />)
    const input = screen.getByLabelText('photoUpload.selectFile') as HTMLInputElement
    const clickSpy = vi.spyOn(input, 'click')
    const chooseBtn = screen.getByRole('button', { name: 'photoUpload.selectFile' })
    chooseBtn.focus()
    await user.keyboard('{Enter}')
    expect(clickSpy).toHaveBeenCalledTimes(1)
  })

  it('the close X is an IconButton with an accessible name and fires onClose (fails if the close control loses its accessible name or wiring)', () => {
    const onClose = vi.fn()
    render(<PhotoUpload vin="V1" onSuccess={vi.fn()} onClose={onClose} />)
    const close = screen.getByRole('button', { name: 'common:close' })
    expect(close).toHaveAttribute('aria-label', 'common:close')
    close.click()
    expect(onClose).toHaveBeenCalled()
  })

  // Final-review I4 regression fence: `set_as_main` has no fieldErrors-wired
  // Field (it's a bare Checkbox), so a 422 naming it used to write to
  // fieldErrors state, render nothing, and — under the old
  // `problems.length > 0 ? fieldErrors : setError(...)` gate — suppress the
  // banner too. applyControlledFieldErrors's attached/unhandled split must
  // still surface the banner when nothing attached.
  it('a 422 naming ONLY set_as_main (no render target) shows the banner, not silence', async () => {
    const user = userEvent.setup({ applyAccept: false })
    postMock.mockRejectedValueOnce({
      isAxiosError: true,
      message: 'Request failed with status code 422',
      response: {
        status: 422,
        data: { detail: [{ type: 'bool_parsing', loc: ['body', 'set_as_main'], msg: 'Invalid boolean' }] },
      },
    })
    render(<PhotoUpload vin="V1" onSuccess={vi.fn()} onClose={vi.fn()} />)
    const file = new File(['ÿØÿ'], 'front.jpg', { type: 'image/jpeg' })
    await user.upload(fileInput(), file)
    await user.click(screen.getByRole('button', { name: 'photoUpload.uploadBtn' }))
    await vi.waitFor(() => expect(postMock).toHaveBeenCalledTimes(1))
    expect(
      await screen.findByText('Failed to photoUpload.uploadAction. Please check your input.')
    ).toBeInTheDocument()
  })
})
