import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { act, fireEvent, render, screen } from '../../__tests__/test-utils'
import userEvent from '@testing-library/user-event'

const apiGet = vi.fn()
const apiPost = vi.fn()
const apiPatch = vi.fn()
vi.mock('../../services/api', () => ({
  default: {
    // Only /settings/public: the sticker and OCR switches.
    get: (...args: unknown[]) => apiGet(...args),
    post: (...args: unknown[]) => apiPost(...args),
    patch: (...args: unknown[]) => apiPatch(...args),
  },
}))
vi.mock('../../hooks/useCurrencyPreference', () => ({
  useCurrencyPreference: () => ({ currencyCode: 'USD', locale: 'en-US', formatCurrency: vi.fn() }),
}))
vi.mock('../../hooks/useUnitPreference', async () => {
  const { IMPERIAL_UNITS } = await import('@/__tests__/factories')
  // UnitSession reads the account half too; same answer, nothing to pin here.
  const unitPreference = () => ({ system: 'imperial', showBoth: false, units: IMPERIAL_UNITS }) 
  return { useUnitPreference: unitPreference,
    useAccountUnitPreference: unitPreference}
})

import WindowStickerUpload from '../WindowStickerUpload'

// What the upload returns: the vehicle row's sticker columns, Decimals as strings.
const extracted = {
  vin: 'V1',
  window_sticker_file_path: '/data/sticker.pdf',
  window_sticker_uploaded_at: '2026-09-29T00:00:00',
  msrp_base: '30000.00',
  msrp_options: null,
  msrp_total: '31500.00',
  destination_charge: '1500.00',
  fuel_economy_city_l_per_100km: '7.84',
  fuel_economy_highway_l_per_100km: '6.53',
  fuel_economy_combined_l_per_100km: null,
  standard_equipment: null,
  optional_equipment: null,
  assembly_location: 'Ohio',
  exterior_color: 'Blu',
  interior_color: 'Black',
  sticker_engine_description: '2.0L I4',
  sticker_transmission_description: 'CVT',
  sticker_drivetrain: null,
  wheel_specs: null,
  tire_specs: null,
  warranty_powertrain: '5yr/60k',
  warranty_basic: null,
  environmental_rating_ghg: '7',
  environmental_rating_smog: '7',
  window_sticker_options_detail: null,
  window_sticker_packages: null,
  window_sticker_parser_used: 'honda',
  window_sticker_confidence_score: '90.00',
}

beforeEach(() => {
  vi.clearAllMocks()
  // Both switches on, as on a fresh install.
  apiGet.mockResolvedValue({ data: { settings: [] } })
  apiPost.mockResolvedValue({ data: extracted })
  apiPatch.mockResolvedValue({ data: extracted })
})

const reachReview = async (user: ReturnType<typeof userEvent.setup>) => {
  const input = document.querySelector('input[type="file"]') as HTMLInputElement
  await user.upload(input, new File(['%PDF-1.4'], 'sticker.pdf', { type: 'application/pdf' }))
  await user.click(screen.getByRole('button', { name: 'windowSticker.uploadAndExtract' }))
  await screen.findByRole('button', { name: 'windowSticker.misc.saveData' })
}

const save = (user: ReturnType<typeof userEvent.setup>) =>
  user.click(screen.getByRole('button', { name: 'windowSticker.misc.saveData' }))

const patched = async (): Promise<Record<string, unknown>> => {
  await vi.waitFor(() => expect(apiPatch).toHaveBeenCalledTimes(1))
  expect(apiPatch.mock.calls[0][0]).toBe('/vehicles/V1/window-sticker/data')
  return apiPatch.mock.calls[0][1]
}

describe('WindowStickerUpload review: the PATCH carries only what the user changed', () => {
  it('an untouched review saves nothing and still finishes', async () => {
    const user = userEvent.setup({ applyAccept: false })
    const onSuccess = vi.fn()
    render(<WindowStickerUpload vin="V1" onSuccess={onSuccess} onClose={vi.fn()} />)
    await reachReview(user)
    await save(user)
    await vi.waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1), { timeout: 2000 })
    expect(apiPatch).not.toHaveBeenCalled()
  })

  it('clearing the exterior colour posts only that null', async () => {
    const user = userEvent.setup({ applyAccept: false })
    render(<WindowStickerUpload vin="V1" onSuccess={vi.fn()} onClose={vi.fn()} />)
    await reachReview(user)
    await user.clear(screen.getByLabelText('detail.misc.exteriorColor'))
    await save(user)
    expect(await patched()).toStrictEqual({ exterior_color: null })
  })

  it('the drivetrain can be entered', async () => {
    const user = userEvent.setup({ applyAccept: false })
    render(<WindowStickerUpload vin="V1" onSuccess={vi.fn()} onClose={vi.fn()} />)
    await reachReview(user)
    await user.type(screen.getByLabelText('detail.misc.drivetrain'), 'AWD')
    await save(user)
    expect(await patched()).toStrictEqual({ sticker_drivetrain: 'AWD' })
  })

  it('reads a comma-decimal MSRP as 528.25, not a 100x-inflated 52825', async () => {
    const user = userEvent.setup({ applyAccept: false })
    render(<WindowStickerUpload vin="V1" onSuccess={vi.fn()} onClose={vi.fn()} />)
    await reachReview(user)
    await user.clear(screen.getByLabelText('detail.misc.basePrice ($)'))
    await user.type(screen.getByLabelText('detail.misc.basePrice ($)'), '528,25')
    await save(user)
    expect(await patched()).toStrictEqual({ msrp_base: 528.25 })
  })

  it('unparseable MSRP text is an inline error, not a silent blank', async () => {
    const user = userEvent.setup({ applyAccept: false })
    render(<WindowStickerUpload vin="V1" onSuccess={vi.fn()} onClose={vi.fn()} />)
    await reachReview(user)
    await user.clear(screen.getByLabelText('detail.misc.basePrice ($)'))
    await user.type(screen.getByLabelText('detail.misc.basePrice ($)'), 'abc')
    await save(user)
    expect(await screen.findByRole('alert')).toHaveTextContent('common:validation.amount.invalid')
    expect(apiPatch).not.toHaveBeenCalled()
  })

  // money-fits: the API takes an MSRP from 0 to MONEY_MAX (9,999,999,999.99).
  it.each([
    ['10000000000', 'common:validation.amount.tooLarge'],
    ['-5', 'common:validation.amount.negative'],
  ])('an MSRP of %s is an inline error and nothing is sent', async (typed, message) => {
    const user = userEvent.setup({ applyAccept: false })
    render(<WindowStickerUpload vin="V1" onSuccess={vi.fn()} onClose={vi.fn()} />)
    await reachReview(user)
    await user.clear(screen.getByLabelText('detail.misc.totalMsrp ($)'))
    await user.type(screen.getByLabelText('detail.misc.totalMsrp ($)'), typed)
    await save(user)
    expect(await screen.findByRole('alert')).toHaveTextContent(message)
    expect(apiPatch).not.toHaveBeenCalled()
  })

  it('a field error clears when the field is edited', async () => {
    const user = userEvent.setup({ applyAccept: false })
    render(<WindowStickerUpload vin="V1" onSuccess={vi.fn()} onClose={vi.fn()} />)
    await reachReview(user)
    // By id: the label carries the currency symbol now.
    const base = document.getElementById('sticker-msrp_base') as HTMLInputElement
    const total = document.getElementById('sticker-msrp_total') as HTMLInputElement
    await user.clear(base)
    await user.type(base, '-5')
    await user.clear(total)
    await user.type(total, '-5')
    await save(user)
    expect(await screen.findAllByText('common:validation.amount.negative')).toHaveLength(2)

    await user.clear(base)
    await user.type(base, '31000')
    expect(base).not.toHaveAttribute('aria-invalid')
    // The total is still -5, so its error is the only one left.
    expect(screen.getAllByText('common:validation.amount.negative')).toHaveLength(1)
    expect(total).toHaveAttribute('aria-invalid', 'true')
    expect(apiPatch).not.toHaveBeenCalled()
  })

  it('a 422 on a field the old list lacked lands inline, not in the banner', async () => {
    const user = userEvent.setup({ applyAccept: false })
    apiPatch.mockRejectedValueOnce({
      isAxiosError: true,
      message: 'Request failed with status code 422',
      // The envelope the backend really sends (utils/error_handlers.py): `details`.
      response: {
        status: 422,
        data: {
          error: true,
          message: 'Validation error',
          details: [
            { type: 'string_too_long', loc: ['body', 'environmental_rating_ghg'], msg: 'String should have at most 10 characters' },
          ],
        },
      },
    })
    render(<WindowStickerUpload vin="V1" onSuccess={vi.fn()} onClose={vi.fn()} />)
    await reachReview(user)
    await user.type(screen.getByLabelText('windowSticker.misc.greenhouseGas'), '+')
    await save(user)
    await vi.waitFor(() => expect(apiPatch).toHaveBeenCalledTimes(1))
    expect(await screen.findByRole('alert')).toHaveTextContent('String should have at most 10 characters')
    expect(screen.queryByText('Failed to windowSticker.saveAction. Please check your input.')).not.toBeInTheDocument()
  })
})

describe('WindowStickerUpload review: fuel economy in the user\'s unit', () => {
  it('shows the stored L/100 km as mpg and posts an edit back as L/100 km', async () => {
    const user = userEvent.setup({ applyAccept: false })
    render(<WindowStickerUpload vin="V1" onSuccess={vi.fn()} onClose={vi.fn()} />)
    await reachReview(user)
    const city = screen.getByLabelText('detail.misc.city') as HTMLInputElement
    // 235.215 / 7.84 = 30.0 mpg
    expect(Number(city.value)).toBeCloseTo(30, 0)
    await user.clear(city)
    await user.type(city, '25')
    await save(user)
    const body = await patched()
    expect(Object.keys(body)).toEqual(['fuel_economy_city_l_per_100km'])
    expect(body.fuel_economy_city_l_per_100km as number).toBeCloseTo(9.41, 2)
  })

  it('an untouched fuel economy is not re-posted when another field changes', async () => {
    const user = userEvent.setup({ applyAccept: false })
    render(<WindowStickerUpload vin="V1" onSuccess={vi.fn()} onClose={vi.fn()} />)
    await reachReview(user)
    await user.clear(screen.getByLabelText('detail.misc.interiorColor'))
    await user.type(screen.getByLabelText('detail.misc.interiorColor'), 'Gray')
    await save(user)
    expect(await patched()).toStrictEqual({ interior_color: 'Gray' })
  })
})

describe('WindowStickerUpload review: economy and ratings the OCR missed', () => {
  const missed = {
    ...extracted,
    fuel_economy_city_l_per_100km: null,
    fuel_economy_highway_l_per_100km: null,
    fuel_economy_combined_l_per_100km: null,
    environmental_rating_ghg: null,
    environmental_rating_smog: null,
  }

  const byId = (id: string): HTMLInputElement | null => document.querySelector<HTMLInputElement>(`#${id}`)

  it('the review offers fuel economy and ratings the OCR missed', async () => {
    const user = userEvent.setup({ applyAccept: false })
    apiPost.mockResolvedValue({ data: missed })
    render(<WindowStickerUpload vin="V1" onSuccess={vi.fn()} onClose={vi.fn()} />)
    await reachReview(user)
    expect(byId('sticker-fuel_economy_city_l_per_100km')).not.toBeNull()
    expect(byId('sticker-environmental_rating_ghg')).not.toBeNull()
  })

  it('an economy and a rating typed into an empty review are sent', async () => {
    const user = userEvent.setup({ applyAccept: false })
    apiPost.mockResolvedValue({ data: missed })
    render(<WindowStickerUpload vin="V1" onSuccess={vi.fn()} onClose={vi.fn()} />)
    await reachReview(user)
    const city = byId('sticker-fuel_economy_city_l_per_100km')
    const ghg = byId('sticker-environmental_rating_ghg')
    expect(city).not.toBeNull()
    expect(ghg).not.toBeNull()
    await user.type(city!, '30')
    await user.type(ghg!, '8')
    await save(user)
    const body = await patched()
    // The empty economy fields it didn't touch stay out of the PATCH.
    expect(Object.keys(body).sort()).toEqual(['environmental_rating_ghg', 'fuel_economy_city_l_per_100km'])
    expect(body.environmental_rating_ghg).toBe('8')
    // 30 US mpg is 235.215 / 30 = 7.84 L/100 km.
    expect(Math.abs((body.fuel_economy_city_l_per_100km as number) - 7.84)).toBeLessThan(0.01)
  })
})

describe('WindowStickerUpload review: money in the user\'s currency', () => {
  it('option prices show in the user\'s currency and Included stays a word', async () => {
    const user = userEvent.setup({ applyAccept: false })
    apiPost.mockResolvedValue({
      data: { ...extracted, window_sticker_options_detail: { Sunroof: '1500.00', 'Floor mats': 'Included' } },
    })
    render(<WindowStickerUpload vin="V1" onSuccess={vi.fn()} onClose={vi.fn()} />)
    await reachReview(user)
    expect(screen.getByText('$1,500.00')).toBeInTheDocument()
    expect(screen.getByText('Floor mats')).toBeInTheDocument()
    expect(screen.queryByText('$Included')).not.toBeInTheDocument()
  })

  it('the MSRP inputs name the currency', async () => {
    const user = userEvent.setup({ applyAccept: false })
    render(<WindowStickerUpload vin="V1" onSuccess={vi.fn()} onClose={vi.fn()} />)
    await reachReview(user)
    expect(screen.getByLabelText('detail.misc.basePrice ($)')).toBeInTheDocument()
  })

  it('MSRP placeholders carry no grouping', async () => {
    const user = userEvent.setup({ applyAccept: false })
    render(<WindowStickerUpload vin="V1" onSuccess={vi.fn()} onClose={vi.fn()} />)
    await reachReview(user)
    // By id, so this fails on the comma and not on the label it also changes.
    // A comma is the decimal point in most of the supported locales.
    for (const key of ['msrp_base', 'msrp_options', 'destination_charge', 'msrp_total']) {
      const input = document.getElementById(`sticker-${key}`) as HTMLInputElement | null
      expect(input, key).not.toBeNull()
      expect(input!.placeholder, key).not.toBe('')
      expect(input!.placeholder, key).not.toContain(',')
    }
  })
})

// The reload timer runs on fake timers. user-event drains on a real
// setTimeout, so once they're on, clicks go through fireEvent.
describe('WindowStickerUpload review: a save reloads the page once', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  const fakeTimers = () => vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
  const button = (name: string) => screen.getByRole('button', { name })
  const runTimers = () =>
    act(async () => {
      await vi.advanceTimersByTimeAsync(2000)
    })

  it('Cancel inside the second after a save reloads once and never as a cancel', async () => {
    const user = userEvent.setup({ applyAccept: false })
    const onSuccess = vi.fn()
    const onClose = vi.fn()
    render(<WindowStickerUpload vin="V1" onSuccess={onSuccess} onClose={onClose} />)
    await reachReview(user)
    fakeTimers()
    fireEvent.click(button('windowSticker.misc.saveData'))
    fireEvent.click(button('windowSticker.misc.cancel'))
    await runTimers()
    expect(onSuccess).toHaveBeenCalledTimes(1)
    expect(onClose).not.toHaveBeenCalled()
  })

  it('closing the drawer before the second is up reloads nothing afterwards', async () => {
    const user = userEvent.setup({ applyAccept: false })
    const onSuccess = vi.fn()
    const { unmount } = render(<WindowStickerUpload vin="V1" onSuccess={onSuccess} onClose={vi.fn()} />)
    await reachReview(user)
    fakeTimers()
    fireEvent.click(button('windowSticker.misc.saveData'))
    unmount()
    await runTimers()
    expect(onSuccess).not.toHaveBeenCalled()
  })

  it('saving an untouched review twice then cancelling still reloads once', async () => {
    const user = userEvent.setup({ applyAccept: false })
    const onSuccess = vi.fn()
    const onClose = vi.fn()
    render(<WindowStickerUpload vin="V1" onSuccess={onSuccess} onClose={onClose} />)
    await reachReview(user)
    fakeTimers()
    fireEvent.click(button('windowSticker.misc.saveData'))
    expect(button('windowSticker.misc.saveData')).toBeDisabled()
    fireEvent.click(button('windowSticker.misc.saveData'))
    fireEvent.click(button('windowSticker.misc.cancel'))
    await runTimers()
    expect(onSuccess).toHaveBeenCalledTimes(1)
    expect(onClose).not.toHaveBeenCalled()
    expect(apiPatch).not.toHaveBeenCalled()
  })

  // Holds the PATCH open and records whether it had landed when the page reloaded.
  const holdPatch = () => {
    const state = { landed: false, land: (_value: unknown): void => {} }
    apiPatch.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          state.land = (value) => {
            state.landed = true
            resolve(value)
          }
        })
    )
    return state
  }

  const editColour = async (user: ReturnType<typeof userEvent.setup>) => {
    await user.clear(screen.getByLabelText('detail.misc.exteriorColor'))
    await user.type(screen.getByLabelText('detail.misc.exteriorColor'), 'Red')
  }

  it('Cancel while the PATCH is out waits for it: one reload, after the edits land', async () => {
    const user = userEvent.setup({ applyAccept: false })
    const patch = holdPatch()
    const reloadedAfterPatch: boolean[] = []
    const onSuccess = vi.fn(() => {
      reloadedAfterPatch.push(patch.landed)
    })
    const onClose = vi.fn()
    render(<WindowStickerUpload vin="V1" onSuccess={onSuccess} onClose={onClose} />)
    await reachReview(user)
    await editColour(user)
    fakeTimers()
    fireEvent.click(button('windowSticker.misc.saveData'))
    expect(apiPatch).toHaveBeenCalledTimes(1)
    expect(button('windowSticker.misc.cancel')).toBeDisabled()
    fireEvent.click(button('windowSticker.misc.cancel'))
    expect(onClose).not.toHaveBeenCalled()
    expect(onSuccess).not.toHaveBeenCalled()

    await act(async () => {
      patch.land({ data: { ...extracted, exterior_color: 'Red' } })
      await vi.advanceTimersByTimeAsync(2000)
    })
    expect(reloadedAfterPatch).toEqual([true])
    expect(onClose).not.toHaveBeenCalled()
    expect(apiPatch.mock.calls[0][1]).toStrictEqual({ exterior_color: 'Red' })
  })

  it('the review save gives up after 30 seconds', async () => {
    const user = userEvent.setup({ applyAccept: false })
    render(<WindowStickerUpload vin="V1" onSuccess={vi.fn()} onClose={vi.fn()} />)
    await reachReview(user)
    await editColour(user)
    await save(user)
    await patched()
    expect(apiPatch.mock.calls[0][2]).toMatchObject({ timeout: 30_000 })
  })

  it('unmounting while the PATCH is out reloads nothing when it lands', async () => {
    const user = userEvent.setup({ applyAccept: false })
    const patch = holdPatch()
    const onSuccess = vi.fn()
    const { unmount } = render(<WindowStickerUpload vin="V1" onSuccess={onSuccess} onClose={vi.fn()} />)
    await reachReview(user)
    await editColour(user)
    fakeTimers()
    fireEvent.click(button('windowSticker.misc.saveData'))
    expect(apiPatch).toHaveBeenCalledTimes(1)
    unmount()
    await act(async () => {
      patch.land({ data: { ...extracted, exterior_color: 'Red' } })
      await vi.advanceTimersByTimeAsync(2000)
    })
    expect(onSuccess).not.toHaveBeenCalled()
  })

  // StrictMode mounts, unmounts and mounts again, as the app does in dev.
  it('a save under StrictMode still reloads', async () => {
    const user = userEvent.setup({ applyAccept: false })
    const onSuccess = vi.fn()
    render(<WindowStickerUpload vin="V1" onSuccess={onSuccess} onClose={vi.fn()} />, { reactStrictMode: true })
    await reachReview(user)
    fakeTimers()
    fireEvent.click(button('windowSticker.misc.saveData'))
    await runTimers()
    expect(onSuccess).toHaveBeenCalledTimes(1)
  })

  it('Escape after the reload fired but before the drawer unmounts does not reload again', async () => {
    const user = userEvent.setup({ applyAccept: false })
    const onSuccess = vi.fn()
    const onClose = vi.fn()
    render(<WindowStickerUpload vin="V1" onSuccess={onSuccess} onClose={onClose} />)
    await reachReview(user)
    fakeTimers()
    fireEvent.click(button('windowSticker.misc.saveData'))
    await runTimers()
    expect(onSuccess).toHaveBeenCalledTimes(1)
    fireEvent.keyDown(window, { key: 'Escape' })
    fireEvent.click(button('windowSticker.misc.cancel'))
    expect(onClose).not.toHaveBeenCalled()
    expect(onSuccess).toHaveBeenCalledTimes(1)
  })

  it('Escape or the close button while the PATCH is out does not close ahead of it', async () => {
    const user = userEvent.setup({ applyAccept: false })
    const patch = holdPatch()
    const onSuccess = vi.fn()
    const onClose = vi.fn()
    render(<WindowStickerUpload vin="V1" onSuccess={onSuccess} onClose={onClose} />)
    await reachReview(user)
    await editColour(user)
    fakeTimers()
    fireEvent.click(button('windowSticker.misc.saveData'))
    fireEvent.keyDown(window, { key: 'Escape' })
    fireEvent.click(button('common:close'))
    expect(onClose).not.toHaveBeenCalled()

    await act(async () => {
      patch.land({ data: { ...extracted, exterior_color: 'Red' } })
      await vi.advanceTimersByTimeAsync(2000)
    })
    expect(onSuccess).toHaveBeenCalledTimes(1)
    expect(onClose).not.toHaveBeenCalled()
  })
})

describe('WindowStickerUpload upload: a lost answer still reloads', () => {
  const startUpload = async (user: ReturnType<typeof userEvent.setup>) => {
    const input = document.querySelector('input[type="file"]') as HTMLInputElement
    await user.upload(input, new File(['%PDF-1.4'], 'sticker.pdf', { type: 'application/pdf' }))
    await user.click(screen.getByRole('button', { name: 'windowSticker.uploadAndExtract' }))
  }

  // A timeout lands as ECONNABORTED with no response, the path the network case covers.
  it('the upload gives up after two minutes', async () => {
    const user = userEvent.setup({ applyAccept: false })
    render(<WindowStickerUpload vin="V1" onSuccess={vi.fn()} onClose={vi.fn()} />)
    await startUpload(user)
    await screen.findByRole('button', { name: 'windowSticker.misc.saveData' })
    expect(apiPost).toHaveBeenCalledTimes(1)
    expect(apiPost.mock.calls[0][0]).toBe('/vehicles/V1/window-sticker/upload')
    expect(apiPost.mock.calls[0][2]).toMatchObject({ timeout: 120_000 })
  })

  it('the drawer stays open while the upload is out, and closes with a reload once it lands', async () => {
    const user = userEvent.setup({ applyAccept: false })
    let land: (value: unknown) => void = () => {}
    apiPost.mockImplementationOnce(() => new Promise((resolve) => (land = resolve)))
    const onClose = vi.fn()
    render(<WindowStickerUpload vin="V1" onSuccess={vi.fn()} onClose={onClose} />)
    await startUpload(user)
    const cancel = screen.getByRole('button', { name: 'windowSticker.misc.cancel' })
    expect(cancel).toBeDisabled()
    fireEvent.click(cancel)
    fireEvent.keyDown(window, { key: 'Escape' })
    fireEvent.click(screen.getByRole('button', { name: 'common:close' }))
    expect(onClose).not.toHaveBeenCalled()

    await act(async () => {
      land({ data: extracted })
    })
    await screen.findByRole('button', { name: 'windowSticker.misc.saveData' })
    expect(onClose).not.toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: 'windowSticker.misc.cancel' }))
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(onClose).toHaveBeenCalledWith(true)
    expect(onClose).not.toHaveBeenCalledWith(false)
  })

  // The service commits before the route builds its answer, so a 500 can
  // still mean the sticker is on file.
  it.each([
    ['no response (network or timeout)', { isAxiosError: true, message: 'Network Error', code: 'ERR_NETWORK' }],
    [
      'a 500',
      {
        isAxiosError: true,
        message: 'Request failed with status code 500',
        response: { status: 500, data: { detail: 'Internal server error' } },
      },
    ],
  ])('%s: the error says it may have gone through and Cancel reloads', async (_label, failure) => {
    const user = userEvent.setup({ applyAccept: false })
    apiPost.mockRejectedValueOnce(failure)
    const onClose = vi.fn()
    render(<WindowStickerUpload vin="V1" onSuccess={vi.fn()} onClose={onClose} />)
    await startUpload(user)
    expect(await screen.findByRole('alert')).toHaveTextContent('windowSticker.misc.uploadUnconfirmed')
    await user.click(screen.getByRole('button', { name: 'windowSticker.misc.cancel' }))
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(onClose).toHaveBeenCalledWith(true)
  })

  it('a 4xx with a response keeps the usual error and closes without a reload', async () => {
    const user = userEvent.setup({ applyAccept: false })
    apiPost.mockRejectedValueOnce({
      isAxiosError: true,
      message: 'Request failed with status code 400',
      response: { status: 400, data: { detail: 'Invalid file type' } },
    })
    const onClose = vi.fn()
    render(<WindowStickerUpload vin="V1" onSuccess={vi.fn()} onClose={onClose} />)
    await startUpload(user)
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Invalid file type')
    expect(alert).not.toHaveTextContent('windowSticker.misc.uploadUnconfirmed')
    await user.click(screen.getByRole('button', { name: 'windowSticker.misc.cancel' }))
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(onClose).toHaveBeenCalledWith(false)
  })
})
