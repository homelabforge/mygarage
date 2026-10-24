/**
 * The window sticker test page's Remove button clears the chosen file (#179 sweep).
 *
 * The drop zone's file input is invisible and stretched over the whole panel, so
 * once a file was chosen it sat on top of Remove and a tap opened the picker
 * instead. jsdom has no layout, so these pin STRUCTURE only: no stretched file
 * input exists while a file is chosen, and Remove brings it back. Whether the
 * click really lands on Remove in a browser is G9's E2E half. Remove also clears
 * the last test's result and its error, so nothing describes a file that's gone,
 * and a test still running when the file goes is dropped when it answers.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { toast } from 'sonner'

const apiGet = vi.fn()
const apiPost = vi.fn()
vi.mock('../../services/api', () => ({
  default: {
    get: (...args: unknown[]) => apiGet(...args),
    post: (...args: unknown[]) => apiPost(...args),
  },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('../../hooks/useCurrencyPreference', () => ({
  useCurrencyPreference: () => ({ currencyCode: 'USD', locale: 'en-US' }),
}))

import WindowStickerTest from '../WindowStickerTest'

const OVERLAY_INPUT = 'input[type="file"].inset-0'

const FAILED_RESULT = {
  success: false,
  parser_name: 'FordParser',
  manufacturer_detected: 'Ford',
  raw_text: null,
  extracted_data: null,
  validation_warnings: [],
  error: 'No MSRP found on the sticker',
}

const SUCCESS_RESULT = {
  success: true,
  parser_name: 'ToyotaParser',
  manufacturer_detected: 'Toyota',
  raw_text: null,
  extracted_data: null,
  validation_warnings: [],
  error: null,
}

/** Renders the page at its real route and waits for the parser list load to settle. */
async function renderPage(): Promise<HTMLElement> {
  const { container } = render(
    <MemoryRouter initialEntries={['/vehicles/1HGCM82633A004352/window-sticker-test']}>
      <Routes>
        <Route path="/vehicles/:vin/window-sticker-test" element={<WindowStickerTest />} />
      </Routes>
    </MemoryRouter>,
  )
  await waitFor(() => expect(apiGet).toHaveBeenCalledWith('/vehicles/window-sticker/parsers'))
  return container
}

/** Picks a file through the overlay input, the way the picker hands one back. */
function chooseFile(container: HTMLElement, name = 'sticker.pdf'): void {
  const input = container.querySelector<HTMLInputElement>(OVERLAY_INPUT)
  expect(input).not.toBeNull()
  const file = new File(['%PDF-1.4'], name, { type: 'application/pdf' })
  fireEvent.change(input as HTMLInputElement, { target: { files: [file] } })
}

/** A promise the test settles by hand, so a request can still be running when Remove is clicked. */
function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void; reject: (reason: unknown) => void } {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

function testButton(): HTMLElement {
  return screen.getByRole('button', { name: /^windowSticker\.(testExtraction|processing)$/ })
}

/** No parsers; `publicSettings` as /settings/public (both switches on when empty). */
function serve(publicSettings: { key: string; value: string }[] = []): void {
  apiGet.mockImplementation((url: string) =>
    Promise.resolve({ data: url === '/settings/public' ? { settings: publicSettings } : [] }),
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  serve()
})

describe('WindowStickerTest drop zone', () => {
  it('takes the invisible file input off the panel once a file is chosen', async () => {
    const container = await renderPage()

    chooseFile(container)

    expect(screen.getByText('sticker.pdf')).toBeInTheDocument()
    expect(container.querySelector(OVERLAY_INPUT)).toBeNull()
  })

  // The last line kills a mutant where the input never comes back after Remove
  // (a removed-once latch on the render condition); checked once by hand.
  it('Remove clears the chosen file and puts the picker input back', async () => {
    const container = await renderPage()
    chooseFile(container)
    expect(container.querySelector(OVERLAY_INPUT)).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'common:remove' }))

    expect(screen.queryByText('sticker.pdf')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'windowSticker.testExtraction' })).toBeDisabled()
    expect(container.querySelector(OVERLAY_INPUT)).not.toBeNull()
  })

  // Guard: passes before G8 fix round 1. Kills a mutant where a file choice is
  // ignored once the run counter has moved (Remove moves it); checked once by hand.
  it('takes a new file chosen after Remove', async () => {
    const container = await renderPage()
    chooseFile(container)
    fireEvent.click(screen.getByRole('button', { name: 'common:remove' }))

    chooseFile(container, 'other.pdf')

    expect(screen.getByText('other.pdf')).toBeInTheDocument()
    expect(screen.queryByText('sticker.pdf')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'windowSticker.testExtraction' })).toBeEnabled()
    expect(container.querySelector(OVERLAY_INPUT)).toBeNull()
  })

  // Both kinds of result, so neither half of a "clear only one kind" mutant
  // survives: the failed case kills `r?.success ? null : r`, the successful
  // case kills `r?.success ? r : null`. The failed one has its error on screen.
  it.each([
    ['failed', FAILED_RESULT, ['No MSRP found on the sticker', 'windowSticker.extractionFailed', 'FordParser']],
    ['successful', SUCCESS_RESULT, ['windowSticker.extractionSuccess', 'ToyotaParser']],
  ])('Remove also clears the last %s result', async (_kind, data, shown) => {
    apiPost.mockResolvedValue({ data })
    const container = await renderPage()
    chooseFile(container)

    fireEvent.click(screen.getByRole('button', { name: 'windowSticker.testExtraction' }))
    expect(await screen.findByText(shown[0])).toBeInTheDocument()
    for (const text of shown) expect(screen.getByText(text)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'common:remove' }))

    for (const text of shown) expect(screen.queryByText(text)).not.toBeInTheDocument()
    expect(screen.getByText('windowSticker.uploadPrompt')).toBeInTheDocument()
  })
})

describe('WindowStickerTest test still running when the file goes', () => {
  it.each([
    ['answer', (d: ReturnType<typeof deferred>): void => d.resolve({ data: SUCCESS_RESULT })],
    ['error', (d: ReturnType<typeof deferred>): void => d.reject(new Error('boom'))],
  ])('a Remove mid-test drops the late %s: no result, no toast, loading off', async (_kind, settle) => {
    const request = deferred()
    apiPost.mockReturnValue(request.promise)
    const container = await renderPage()
    chooseFile(container)
    fireEvent.click(screen.getByRole('button', { name: 'windowSticker.testExtraction' }))
    expect(apiPost).toHaveBeenCalledTimes(1)

    fireEvent.click(screen.getByRole('button', { name: 'common:remove' }))
    await act(async () => {
      settle(request)
      await request.promise.catch(() => undefined)
    })

    expect(screen.queryByText('windowSticker.extractionSuccess')).not.toBeInTheDocument()
    expect(screen.queryByText('ToyotaParser')).not.toBeInTheDocument()
    expect(screen.getByText('windowSticker.uploadPrompt')).toBeInTheDocument()
    expect(vi.mocked(toast.success)).not.toHaveBeenCalled()
    expect(vi.mocked(toast.error)).not.toHaveBeenCalled()
    expect(testButton()).toHaveTextContent('windowSticker.testExtraction')
  })

  // Loading goes off at Remove, not later when the dropped run lands, since a
  // dropped run never reaches its own finally.
  it('Remove turns loading off straight away', async () => {
    apiPost.mockReturnValue(deferred().promise)
    const container = await renderPage()
    chooseFile(container)
    fireEvent.click(screen.getByRole('button', { name: 'windowSticker.testExtraction' }))
    expect(testButton()).toHaveTextContent('windowSticker.processing')

    fireEvent.click(screen.getByRole('button', { name: 'common:remove' }))

    expect(testButton()).toHaveTextContent('windowSticker.testExtraction')
  })

  it('dropping another file mid-test drops the old answer and keeps the new file', async () => {
    const request = deferred()
    apiPost.mockReturnValue(request.promise)
    const container = await renderPage()
    chooseFile(container)
    fireEvent.click(screen.getByRole('button', { name: 'windowSticker.testExtraction' }))

    const zone = container.querySelector('.border-dashed') as HTMLElement
    const dropped = new File(['png'], 'other.png', { type: 'image/png' })
    fireEvent.drop(zone, { dataTransfer: { files: [dropped] } })
    await act(async () => {
      request.resolve({ data: SUCCESS_RESULT })
      await request.promise
    })

    expect(screen.getByText('other.png')).toBeInTheDocument()
    expect(screen.queryByText('windowSticker.extractionSuccess')).not.toBeInTheDocument()
    expect(vi.mocked(toast.success)).not.toHaveBeenCalled()
    expect(testButton()).toHaveTextContent('windowSticker.testExtraction')
    expect(testButton()).toBeEnabled()
  })

  // The old run's finally mustn't switch off the new run's spinner, and the new
  // run's own answer still lands.
  it('an old run landing mid-way through a new one leaves the new one alone', async () => {
    const oldRun = deferred()
    const newRun = deferred()
    apiPost.mockReturnValueOnce(oldRun.promise).mockReturnValueOnce(newRun.promise)
    const container = await renderPage()
    chooseFile(container)
    fireEvent.click(screen.getByRole('button', { name: 'windowSticker.testExtraction' }))
    const zone = container.querySelector('.border-dashed') as HTMLElement
    fireEvent.drop(zone, { dataTransfer: { files: [new File(['png'], 'other.png', { type: 'image/png' })] } })
    fireEvent.click(screen.getByRole('button', { name: 'windowSticker.testExtraction' }))
    expect(apiPost).toHaveBeenCalledTimes(2)

    await act(async () => {
      oldRun.resolve({ data: FAILED_RESULT })
      await oldRun.promise
    })

    expect(testButton()).toHaveTextContent('windowSticker.processing')
    expect(screen.queryByText('FordParser')).not.toBeInTheDocument()

    await act(async () => {
      newRun.resolve({ data: SUCCESS_RESULT })
      await newRun.promise
    })

    expect(screen.getByText('ToyotaParser')).toBeInTheDocument()
    expect(testButton()).toHaveTextContent('windowSticker.testExtraction')
    expect(vi.mocked(toast.success)).toHaveBeenCalledTimes(1)
    expect(vi.mocked(toast.error)).not.toHaveBeenCalled()
  })
})

// Settings > Files can switch window stickers, or their OCR, off; the test
// endpoint 409s then, so the page says why instead of offering the form. The
// link to this page stays in the vehicle drawer, so the notice is what a
// user lands on.
describe('WindowStickerTest with a switch off', () => {
  it('with stickers off, shows the notice and no upload control', async () => {
    serve([{ key: 'window_sticker_enabled', value: 'false' }])
    const container = await renderPage()

    expect(await screen.findByText('windowSticker.stickersSwitchedOff')).toBeInTheDocument()
    expect(container.querySelector('input[type="file"]')).toBeNull()
    expect(screen.queryByRole('button', { name: 'windowSticker.testExtraction' })).not.toBeInTheDocument()
  })

  it('with OCR off, says there is nothing to test and offers no upload control', async () => {
    serve([{ key: 'window_sticker_ocr_enabled', value: 'no' }])
    const container = await renderPage()

    expect(await screen.findByText('windowSticker.ocrSwitchedOffTest')).toBeInTheDocument()
    expect(container.querySelector('input[type="file"]')).toBeNull()
    expect(screen.queryByRole('button', { name: 'windowSticker.testExtraction' })).not.toBeInTheDocument()
  })

  // The fallback (Fable F2-4): a failed read hides nothing; the 409 rules.
  it('when the switches cannot be read, the form is offered', async () => {
    apiGet.mockImplementation((url: string) =>
      url === '/settings/public' ? Promise.reject(new Error('down')) : Promise.resolve({ data: [] }),
    )
    const container = await renderPage()

    await waitFor(() => expect(apiGet).toHaveBeenCalledWith('/settings/public'))
    expect(container.querySelector(OVERLAY_INPUT)).not.toBeNull()
    expect(screen.queryByText('windowSticker.stickersSwitchedOff')).not.toBeInTheDocument()
  })
})
