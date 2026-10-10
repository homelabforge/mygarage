import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '../../__tests__/test-utils'
import userEvent from '@testing-library/user-event'

const apiPost = vi.fn()
const apiPatch = vi.fn()
vi.mock('../../services/api', () => ({
  default: {
    post: (...args: unknown[]) => apiPost(...args),
    patch: (...args: unknown[]) => apiPatch(...args),
  },
}))
vi.mock('../../hooks/useCurrencyPreference', () => ({
  useCurrencyPreference: () => ({ currencyCode: 'USD', locale: 'en-US', formatCurrency: vi.fn() }),
}))
vi.mock('../../hooks/useUnitPreference', async () => {
  const { METRIC_UNITS } = await import('@/__tests__/factories')
  return { useUnitPreference: () => ({ system: 'metric', showBoth: false, units: METRIC_UNITS }) }
})

import WindowStickerUpload from '../WindowStickerUpload'

beforeEach(() => {
  vi.clearAllMocks()
  apiPost.mockResolvedValue({ data: { msrp_base: 30000 } })
})

// Drives the form to the post-extraction edit screen (extractedData set),
// which is the real-world precondition for a field-level 422 from the
// `/window-sticker/data` PATCH — the extraction endpoint itself doesn't know
// about individual MSRP/color/warranty fields.
const uploadAndReachEditScreen = async (user: ReturnType<typeof userEvent.setup>) => {
  const input = document.querySelector('input[type="file"]') as HTMLInputElement
  const file = new File(['%PDF-1.4'], 'sticker.pdf', { type: 'application/pdf' })
  await user.upload(input, file)
  await user.click(screen.getByRole('button', { name: 'windowSticker.uploadAndExtract' }))
  await screen.findByRole('button', { name: 'windowSticker.misc.saveData' })
}

// Save only PATCHes what changed, so each 422 case edits a field first.
const editAndSave = async (user: ReturnType<typeof userEvent.setup>) => {
  await user.clear(screen.getByLabelText('detail.misc.basePrice ($)'))
  await user.type(screen.getByLabelText('detail.misc.basePrice ($)'), '31000')
  await user.click(screen.getByRole('button', { name: 'windowSticker.misc.saveData' }))
}

// Final-review I4 regression fence: WindowStickerUpload has 9 fieldErrors-wired
// render targets against ~25 possible ExtractedData payload keys. Before the
// fix, `if (problems.length > 0) { setFieldErrors(...) } else { setError(...) }`
// meant a 422 naming an unmapped key (e.g. fuel_economy_city, which has no
// Field in this form) wrote to fieldErrors state, rendered nothing, and
// suppressed the banner too — total silence on a real backend rejection.
describe('WindowStickerUpload — server-side error wiring (final-review I4)', () => {
  it('a 422 naming ONLY an unmapped field (fuel_economy_city) on save still shows the banner, not silence', async () => {
    const user = userEvent.setup({ applyAccept: false })
    apiPatch.mockRejectedValueOnce({
      isAxiosError: true,
      message: 'Request failed with status code 422',
      response: {
        status: 422,
        data: {
          detail: [{ type: 'greater_than_equal', loc: ['body', 'fuel_economy_city'], msg: 'Input should be >= 0' }],
        },
      },
    })

    render(<WindowStickerUpload vin="V1" onSuccess={vi.fn()} onClose={vi.fn()} />)
    await uploadAndReachEditScreen(user)
    await editAndSave(user)

    await vi.waitFor(() => expect(apiPatch).toHaveBeenCalledTimes(1))
    expect(
      await screen.findByText('Failed to {{action}}. Please check your input.')
    ).toBeInTheDocument()
  })

  it('a 422 naming a mapped field (msrp_base) attaches to that field AND does not ALSO show the generic banner', async () => {
    const user = userEvent.setup({ applyAccept: false })
    apiPatch.mockRejectedValueOnce({
      isAxiosError: true,
      message: 'Request failed with status code 422',
      response: {
        status: 422,
        data: {
          detail: [{ type: 'greater_than_equal', loc: ['body', 'msrp_base'], msg: 'Input should be >= 0' }],
        },
      },
    })

    render(<WindowStickerUpload vin="V1" onSuccess={vi.fn()} onClose={vi.fn()} />)
    await uploadAndReachEditScreen(user)
    await editAndSave(user)

    await vi.waitFor(() => expect(apiPatch).toHaveBeenCalledTimes(1))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Input should be >= 0')
    // Fully-mapped 422 (attached>0, unhandled===0): the field error alone is
    // enough, the generic banner must stay silent — no double-report.
    expect(screen.queryByText('Failed to {{action}}. Please check your input.')).not.toBeInTheDocument()
  })

  it('a 422 with one mapped and one unmapped field shows BOTH the field message and the banner', async () => {
    const user = userEvent.setup({ applyAccept: false })
    apiPatch.mockRejectedValueOnce({
      isAxiosError: true,
      message: 'Request failed with status code 422',
      response: {
        status: 422,
        data: {
          detail: [
            { type: 'greater_than_equal', loc: ['body', 'msrp_base'], msg: 'Input should be >= 0' },
            { type: 'greater_than_equal', loc: ['body', 'fuel_economy_city'], msg: 'Input should be >= 0' },
          ],
        },
      },
    })

    render(<WindowStickerUpload vin="V1" onSuccess={vi.fn()} onClose={vi.fn()} />)
    await uploadAndReachEditScreen(user)
    await editAndSave(user)

    await vi.waitFor(() => expect(apiPatch).toHaveBeenCalledTimes(1))
    await screen.findByRole('alert')
    expect(
      await screen.findByText('Failed to {{action}}. Please check your input.')
    ).toBeInTheDocument()
  })
})

// The comma-decimal MSRP fence (final-review I9) lives in WindowStickerUpload.review.test.tsx,
// asserted on the posted payload now that the input keeps the typed text.

// D1: with a sticker already on file the upload fills empty fields only,
// unless the user turns "keep" off, which sends replace=true.
describe('WindowStickerUpload: keep the values already saved (D1)', () => {
  const uploadAndGetForm = async (user: ReturnType<typeof userEvent.setup>): Promise<FormData> => {
    const input = document.querySelector('input[type="file"]') as HTMLInputElement
    await user.upload(input, new File(['%PDF-1.4'], 'sticker.pdf', { type: 'application/pdf' }))
    await user.click(screen.getByRole('button', { name: 'windowSticker.uploadAndExtract' }))
    await vi.waitFor(() => expect(apiPost).toHaveBeenCalledTimes(1))
    return apiPost.mock.calls[0][1] as FormData
  }

  it('with a sticker on file, keep starts on and the upload sends no replace', async () => {
    const user = userEvent.setup({ applyAccept: false })
    render(<WindowStickerUpload vin="V1" hasExistingSticker onSuccess={vi.fn()} onClose={vi.fn()} />)

    expect(screen.getByRole('checkbox', { name: 'windowSticker.keepSavedValues' })).toBeChecked()
    expect(screen.getByText('windowSticker.keepSavedValuesHint')).toBeInTheDocument()
    const sent = await uploadAndGetForm(user)
    expect(sent.get('file')).toBeInstanceOf(File)
    expect(sent.has('replace')).toBe(false)
  })

  it('turning keep off sends replace=true', async () => {
    const user = userEvent.setup({ applyAccept: false })
    render(<WindowStickerUpload vin="V1" hasExistingSticker onSuccess={vi.fn()} onClose={vi.fn()} />)

    const keep = screen.getByRole('checkbox', { name: 'windowSticker.keepSavedValues' })
    await user.click(keep)
    expect(keep).not.toBeChecked()
    const sent = await uploadAndGetForm(user)
    expect(sent.get('replace')).toBe('true')
  })

  it('a first sticker has no checkbox and sends no replace', async () => {
    const user = userEvent.setup({ applyAccept: false })
    render(<WindowStickerUpload vin="V1" onSuccess={vi.fn()} onClose={vi.fn()} />)

    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
    expect(screen.queryByText('windowSticker.keepSavedValuesHint')).not.toBeInTheDocument()
    const sent = await uploadAndGetForm(user)
    expect(sent.has('replace')).toBe(false)
  })

  it('a scan that read nothing says so instead of the success line', async () => {
    const user = userEvent.setup({ applyAccept: false })
    apiPost.mockResolvedValueOnce({ data: { msrp_base: null, scan_read_nothing: true } })
    render(<WindowStickerUpload vin="V1" hasExistingSticker onSuccess={vi.fn()} onClose={vi.fn()} />)

    await uploadAndGetForm(user)

    expect(await screen.findByText('windowSticker.scanReadNothing')).toBeInTheDocument()
    expect(screen.queryByText('windowSticker.misc.uploadSuccess')).not.toBeInTheDocument()
    // The review still opens, so what the scan missed can be typed in.
    expect(screen.getByRole('button', { name: 'windowSticker.misc.saveData' })).toBeInTheDocument()
  })

  it('a scan that read something shows the success line and no notice', async () => {
    const user = userEvent.setup({ applyAccept: false })
    apiPost.mockResolvedValueOnce({ data: { msrp_base: 30000, scan_read_nothing: false } })
    render(<WindowStickerUpload vin="V1" hasExistingSticker onSuccess={vi.fn()} onClose={vi.fn()} />)

    await uploadAndGetForm(user)

    expect(await screen.findByText('windowSticker.misc.uploadSuccess')).toBeInTheDocument()
    expect(screen.queryByText('windowSticker.scanReadNothing')).not.toBeInTheDocument()
  })
})

// The upload commits the sticker before the review, so closing the drawer
// tells the page whether it has to reload, whichever way it was closed.
describe('WindowStickerUpload: closing says whether a sticker was saved', () => {
  const upload = async (user: ReturnType<typeof userEvent.setup>): Promise<void> => {
    const input = document.querySelector('input[type="file"]') as HTMLInputElement
    await user.upload(input, new File(['%PDF-1.4'], 'sticker.pdf', { type: 'application/pdf' }))
    await user.click(screen.getByRole('button', { name: 'windowSticker.uploadAndExtract' }))
    await screen.findByRole('button', { name: 'windowSticker.misc.saveData' })
  }

  it('cancelling before any upload closes with false', async () => {
    const user = userEvent.setup({ applyAccept: false })
    const onClose = vi.fn()
    render(<WindowStickerUpload vin="V1" onSuccess={vi.fn()} onClose={onClose} />)

    await user.click(screen.getByRole('button', { name: 'windowSticker.misc.cancel' }))

    expect(onClose).toHaveBeenCalledTimes(1)
    expect(onClose).toHaveBeenCalledWith(false)
  })

  it('cancelling the review after an upload closes with true', async () => {
    const user = userEvent.setup({ applyAccept: false })
    const onClose = vi.fn()
    render(<WindowStickerUpload vin="V1" onSuccess={vi.fn()} onClose={onClose} />)
    await upload(user)

    await user.click(screen.getByRole('button', { name: 'windowSticker.misc.cancel' }))

    expect(onClose).toHaveBeenCalledTimes(1)
    expect(onClose).toHaveBeenCalledWith(true)
  })

  it('escaping the drawer after an upload closes with true', async () => {
    const user = userEvent.setup({ applyAccept: false })
    const onClose = vi.fn()
    render(<WindowStickerUpload vin="V1" onSuccess={vi.fn()} onClose={onClose} />)
    await upload(user)

    await user.keyboard('{Escape}')

    expect(onClose).toHaveBeenCalledTimes(1)
    expect(onClose).toHaveBeenCalledWith(true)
  })

  it('a saved review finishes through onSuccess alone, so the page reloads once', async () => {
    const user = userEvent.setup({ applyAccept: false })
    const onSuccess = vi.fn()
    const onClose = vi.fn()
    render(<WindowStickerUpload vin="V1" onSuccess={onSuccess} onClose={onClose} />)
    await upload(user)

    await user.click(screen.getByRole('button', { name: 'windowSticker.misc.saveData' }))

    await vi.waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1), { timeout: 2000 })
    expect(onClose).not.toHaveBeenCalled()
  })
})
