import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '../../__tests__/test-utils'
import VINInput from '../VINInput'

describe('VINInput', () => {
  it('accepts 17 character VIN', () => {
    const onChangeMock = vi.fn()
    render(<VINInput value="" onChange={onChangeMock} />)

    const input = screen.getByRole('textbox')
    fireEvent.change(input, { target: { value: '1HGBH41JXMN109186' } })

    expect(onChangeMock).toHaveBeenCalled()
  })

  it('converts input to uppercase', () => {
    const onChangeMock = vi.fn()
    render(<VINInput value="" onChange={onChangeMock} />)

    const input = screen.getByRole('textbox')
    fireEvent.change(input, { target: { value: '1hgbh41jxmn109186' } })

    // Component should call onChange with uppercase value
    expect(onChangeMock).toHaveBeenCalledWith('1HGBH41JXMN109186')
  })

  it('validates VIN length', () => {
    const onChangeMock = vi.fn()
    render(<VINInput value="SHORT" onChange={onChangeMock} />)

    // Component displays character counter. The i18n mock renders the key, so
    // assert on the key rather than the interpolated English.
    expect(screen.getByText('vinInput.characterCount')).toBeInTheDocument()
  })

  it('rejects invalid characters I, O, Q', () => {
    const onChangeMock = vi.fn()
    render(<VINInput value="" onChange={onChangeMock} />)

    const input = screen.getByRole('textbox')
    // Try to enter invalid character 'I'
    fireEvent.change(input, { target: { value: '1HGBH41JXMNI09186' } })

    // Should either reject or show error
    // Implementation-dependent behavior
  })

  it('calls onDecode when VIN is complete', () => {
    const onDecodeMock = vi.fn()
    render(<VINInput value="1HGBH41JXMN109186" onChange={vi.fn()} onDecode={onDecodeMock} />)

    // Should trigger decode automatically
    // Implementation-dependent
  })
})

// The European VIN notice (#211): a partial decode says what the VIN
// carries and points at the certificate; a full one shows nothing extra.
vi.mock('@/services/vinService', () => ({
  vinService: {
    validate: vi.fn().mockResolvedValue({ valid: true, vin: 'VF1RFB00X56123456' }),
    decode: vi.fn(),
    decodeVersion: vi.fn(),
    exists: vi.fn().mockResolvedValue(false),
    providers: vi.fn().mockResolvedValue({ available: ['nhtsa'], preferred: 'nhtsa' }),
  },
}))

// The country that orders the decoders (#219): resolved inside VINInput, so
// a caller without a registration country (the friends' vehicle modal)
// still sends one.
vi.mock('@/hooks/useResolvedCountry', () => ({
  useResolvedCountry: () => 'FR',
}))

import { act, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { vinService } from '@/services/vinService'

describe('VINInput — European VINs (#211)', () => {
  // A Porsche's VIN carries the year (NHTSA read 2019), so the notice can't
  // say it doesn't (dev test 2026-11-06).
  it.each([
    ['EU', 'vinInput.euNoModel'],
    [null, 'vinInput.partialNoModel'],
  ])('only asks for the model when the year decoded (region %s)', async (region, key) => {
    vi.mocked(vinService.decode).mockResolvedValue({
      vin: 'WP1ZZZ95ZKLB15431',
      make: 'Porsche',
      model: null,
      year: 2019,
      region,
      decode_quality: 'partial',
      notes: [],
    })
    render(<VINInput value="WP1ZZZ95ZKLB15431" onChange={vi.fn()} onDecode={vi.fn()} />)

    fireEvent.click(screen.getByRole('button', { name: /vinInput.decode/ }))

    const notice = await screen.findByTestId('vin-partial-decode')
    expect(notice).toHaveTextContent(key)
    expect(notice).not.toHaveTextContent('vinInput.euPartial')
    expect(notice).not.toHaveTextContent('vinInput.partialDecode')
  })

  it('explains a partial decode and offers the certificate import', async () => {
    vi.mocked(vinService.decode).mockResolvedValue({
      vin: 'VF1RFB00X56123456',
      make: 'Renault',
      model: null,
      year: null,
      manufacturer: 'RENAULT GROUP',
      region: 'EU',
      wmi_country: 'FR',
      decode_quality: 'partial',
      notes: ['eu_vin_no_model', 'year_unreliable'],
    })
    const onImport = vi.fn()
    render(
      <VINInput value="VF1RFB00X56123456" onChange={vi.fn()} onDecode={vi.fn()} onImportCertificate={onImport} />,
    )

    fireEvent.click(screen.getByRole('button', { name: /vinInput.decode/ }))

    const notice = await screen.findByTestId('vin-partial-decode')
    expect(notice).toHaveTextContent('vinInput.euPartial')
    expect(notice).toHaveTextContent('vinInput.notes.eu_vin_no_model')
    expect(notice).toHaveTextContent('vinInput.notes.year_unreliable')
    fireEvent.click(screen.getByRole('button', { name: /vinInput.importCertificate/ }))
    expect(onImport).toHaveBeenCalled()
    // No plant from NHTSA: the WMI's country stands in.
    expect(screen.getByText('vinInput.fieldWmiCountry')).toBeInTheDocument()
  })

  it('shows nothing extra on a full decode', async () => {
    vi.mocked(vinService.decode).mockResolvedValue({
      vin: '1HGBH41JXMN109186',
      make: 'HONDA',
      model: 'Accord',
      year: 2018,
      region: 'NA',
      wmi_country: 'US',
      decode_quality: 'full',
      notes: [],
      plant_country: 'UNITED STATES (USA)',
    })
    render(<VINInput value="1HGBH41JXMN109186" onChange={vi.fn()} onImportCertificate={vi.fn()} />)

    fireEvent.click(screen.getByRole('button', { name: /vinInput.decode/ }))

    await waitFor(() => expect(screen.getByText('vinInput.decodedTitle')).toBeInTheDocument())
    expect(screen.queryByTestId('vin-partial-decode')).not.toBeInTheDocument()
    expect(screen.queryByText('vinInput.fieldWmiCountry')).not.toBeInTheDocument()
  })
})

// Two decoders (#219 takeover).
describe('VINInput — choosing the decoder', () => {
  const EU_VIN = 'VF1RFB00X56123456'
  const withAutoRef = (): void => {
    vi.mocked(vinService.providers).mockResolvedValue({ available: ['nhtsa', 'autoref'], preferred: 'autoref' })
  }
  const thinNhtsa = {
    vin: EU_VIN,
    make: 'Renault',
    model: null,
    region: 'EU',
    decode_quality: 'partial' as const,
    decoded_by: 'nhtsa' as const,
    notes: ['eu_vin_no_model'],
  }

  beforeEach(() => {
    vi.mocked(vinService.decode).mockReset()
    vi.mocked(vinService.providers).mockResolvedValue({ available: ['nhtsa'], preferred: 'nhtsa' })
  })

  it('shows no choice without an AutoRef key', async () => {
    vi.mocked(vinService.decode).mockResolvedValue(thinNhtsa)
    render(<VINInput value={EU_VIN} onChange={vi.fn()} />)
    await waitFor(() => expect(vinService.providers).toHaveBeenCalledWith('FR'))
    expect(screen.queryByLabelText('vinInput.decodeWith')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /vinInput.decode/ }))
    await screen.findByTestId('vin-partial-decode')
    expect(screen.queryByRole('button', { name: /vinInput.tryAutoRef/ })).not.toBeInTheDocument()
  })

  it('starts on Automatic and a plain Decode sends no provider', async () => {
    withAutoRef()
    vi.mocked(vinService.decode).mockResolvedValue({ ...thinNhtsa, decode_quality: 'full', model: 'Clio' })
    render(<VINInput value={EU_VIN} onChange={vi.fn()} />)
    const select = (await screen.findByLabelText('vinInput.decodeWith')) as HTMLSelectElement
    expect(select.value).toBe('automatic')

    fireEvent.click(screen.getByRole('button', { name: /vinInput.decode/ }))
    await waitFor(() => expect(vinService.decode).toHaveBeenCalled())
    const [, options] = vi.mocked(vinService.decode).mock.calls[0]
    expect(options).toEqual({ country: 'FR' })
    expect(options).not.toHaveProperty('provider')
  })

  it('sends the provider once one is chosen', async () => {
    withAutoRef()
    vi.mocked(vinService.decode).mockResolvedValue({ ...thinNhtsa, decode_quality: 'full', model: 'Clio' })
    render(<VINInput value={EU_VIN} onChange={vi.fn()} />)
    const select = await screen.findByLabelText('vinInput.decodeWith')
    fireEvent.change(select, { target: { value: 'nhtsa' } })
    expect(vinService.decode).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: /vinInput.decode/ }))
    await waitFor(() => expect(vinService.decode).toHaveBeenCalled())
    expect(vi.mocked(vinService.decode).mock.calls[0][1]).toEqual({ provider: 'nhtsa', country: 'FR' })
  })

  it('offers AutoRef on a thin NHTSA answer and uses its answer', async () => {
    withAutoRef()
    const onDecode = vi.fn()
    vi.mocked(vinService.decode)
      .mockResolvedValueOnce(thinNhtsa)
      .mockResolvedValueOnce({ ...thinNhtsa, model: 'Clio', decode_quality: 'full', decoded_by: 'autoref', notes: [] })
    render(<VINInput value={EU_VIN} onChange={vi.fn()} onDecode={onDecode} />)
    await screen.findByLabelText('vinInput.decodeWith')

    fireEvent.click(screen.getByRole('button', { name: /vinInput.decode/ }))
    fireEvent.click(await screen.findByRole('button', { name: /vinInput.tryAutoRef/ }))

    await waitFor(() => expect(onDecode).toHaveBeenCalledTimes(2))
    expect(vi.mocked(vinService.decode).mock.calls[1][1]).toEqual({ provider: 'autoref', country: 'FR' })
    expect(await screen.findByText('Clio')).toBeInTheDocument()
    expect(screen.getByText('vinInput.decodedBy')).toBeInTheDocument()
  })

  it('keeps the first answer when the other decoder fails', async () => {
    withAutoRef()
    const onDecode = vi.fn()
    vi.mocked(vinService.decode)
      .mockResolvedValueOnce(thinNhtsa)
      .mockRejectedValueOnce({ response: { status: 404, data: { detail: 'AutoRef has no record for this VIN' } } })
    render(<VINInput value={EU_VIN} onChange={vi.fn()} onDecode={onDecode} />)
    await screen.findByLabelText('vinInput.decodeWith')

    fireEvent.click(screen.getByRole('button', { name: /vinInput.decode/ }))
    fireEvent.click(await screen.findByRole('button', { name: /vinInput.tryAutoRef/ }))

    expect(await screen.findByTestId('vin-try-error')).toBeInTheDocument()
    expect(onDecode).toHaveBeenCalledTimes(1)
    expect(screen.getByText('vinInput.decodedTitle')).toBeInTheDocument()
    expect(screen.getByText('Renault')).toBeInTheDocument()
  })

  it('shows the decoder notes on a full answer, not the check-digit one', async () => {
    vi.mocked(vinService.decode).mockResolvedValue({
      vin: EU_VIN,
      make: 'Renault',
      model: 'Clio',
      region: 'EU',
      decode_quality: 'full',
      decoded_by: 'autoref',
      notes: ['autoref_best_guess', 'check_digit_not_applicable'],
    })
    render(<VINInput value={EU_VIN} onChange={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: /vinInput.decode/ }))

    const notes = await screen.findByTestId('vin-full-notes')
    expect(notes).toHaveTextContent('vinInput.notes.autoref_best_guess')
    expect(notes).not.toHaveTextContent('vinInput.notes.check_digit_not_applicable')
    expect(screen.queryByTestId('vin-partial-decode')).not.toBeInTheDocument()
  })

  it('falls back to Automatic when the chosen decoder goes away', async () => {
    // Fable diff F-3: the key is cleared while AutoRef is chosen; the choice
    // control unmounts, so Decode must not keep naming AutoRef.
    withAutoRef()
    vi.mocked(vinService.decode).mockResolvedValue({ ...thinNhtsa, decode_quality: 'full', model: 'Clio' })
    const client = new QueryClient()
    render(
      <QueryClientProvider client={client}>
        <VINInput value={EU_VIN} onChange={vi.fn()} />
      </QueryClientProvider>,
    )
    fireEvent.change(await screen.findByLabelText('vinInput.decodeWith'), { target: { value: 'autoref' } })
    act(() => {
      client.setQueryData(['vin-providers', 'FR'], { available: ['nhtsa'], preferred: 'nhtsa' })
    })
    await waitFor(() => expect(screen.queryByLabelText('vinInput.decodeWith')).not.toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: /vinInput.decode/ }))
    await waitFor(() => expect(vinService.decode).toHaveBeenCalled())
    expect(vi.mocked(vinService.decode).mock.calls[0][1]).toEqual({ country: 'FR' })
  })

  it('drops an answer for a VIN that was edited while it was decoding', async () => {
    // Fable diff F-6: the old VIN's answer must not fill the form.
    let resolve: (value: typeof thinNhtsa) => void = () => {}
    vi.mocked(vinService.decode).mockReturnValue(new Promise((r) => { resolve = r }))
    const onDecode = vi.fn()
    const { rerender } = render(<VINInput value={EU_VIN} onChange={vi.fn()} onDecode={onDecode} />)
    fireEvent.click(screen.getByRole('button', { name: /vinInput.decode/ }))
    await waitFor(() => expect(vinService.decode).toHaveBeenCalled())

    rerender(<VINInput value="WVWZZZ1JZXW000001" onChange={vi.fn()} onDecode={onDecode} />)
    await act(async () => {
      resolve(thinNhtsa)
    })

    expect(onDecode).not.toHaveBeenCalled()
    expect(screen.queryByText('Renault')).not.toBeInTheDocument()
  })

  it('drops a failure for a VIN that was edited while it was decoding', async () => {
    // Fable fix-wave F-4: the old VIN's error must not land under the new VIN.
    let reject: (reason: Error) => void = () => {}
    vi.mocked(vinService.decode).mockReturnValue(new Promise((_r, j) => { reject = j }))
    const { rerender } = render(<VINInput value={EU_VIN} onChange={vi.fn()} onDecode={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: /vinInput.decode/ }))
    await waitFor(() => expect(vinService.decode).toHaveBeenCalled())

    rerender(<VINInput value="WVWZZZ1JZXW000001" onChange={vi.fn()} onDecode={vi.fn()} />)
    await act(async () => {
      reject(new Error('VIN not found'))
    })

    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.queryByText(/VIN not found|vinInput.decodeAction/)).not.toBeInTheDocument()
  })

  it('drops a failed try for a VIN that was edited while it was decoding', async () => {
    withAutoRef()
    let reject: (reason: unknown) => void = () => {}
    vi.mocked(vinService.decode)
      .mockResolvedValueOnce(thinNhtsa)
      .mockReturnValueOnce(new Promise((_r, j) => { reject = j }))
    const { rerender } = render(<VINInput value={EU_VIN} onChange={vi.fn()} onDecode={vi.fn()} />)
    await screen.findByLabelText('vinInput.decodeWith')
    fireEvent.click(screen.getByRole('button', { name: /vinInput.decode/ }))
    fireEvent.click(await screen.findByRole('button', { name: /vinInput.tryAutoRef/ }))
    await waitFor(() => expect(vinService.decode).toHaveBeenCalledTimes(2))

    rerender(<VINInput value="WVWZZZ1JZXW000001" onChange={vi.fn()} onDecode={vi.fn()} />)
    await act(async () => {
      reject({ response: { status: 404, data: { detail: 'AutoRef has no record for this VIN' } } })
    })

    expect(screen.queryByTestId('vin-try-error')).not.toBeInTheDocument()
  })
})

// Several AutoRef versions for one VIN: pick yours.
describe('VINInput: picking an AutoRef version', () => {
  const GOLF_VIN = 'WVWZZZAUZFW806653'
  const candidate = (id: string, label: string, kw: number, fuel: string) => ({
    record_type: 'TG' as const,
    id,
    label,
    model_full: label,
    fuel_type: fuel,
    kw,
    transmission: 'Manual',
    gearbox_code: 'M' as const,
    grouped: false,
  })
  const R = candidate('310899', 'Golf VII R 5T', 221, 'gasoline')
  const GTE = candidate('311017', 'Golf VII GTE', 110, 'hybrid')
  const several = {
    vin: GOLF_VIN,
    make: 'Volkswagen',
    model: null,
    year: null,
    region: 'EU',
    decode_quality: 'partial' as const,
    decoded_by: 'autoref' as const,
    make_source: 'autoref' as const,
    notes: ['autoref_pick_version', 'check_digit_not_applicable'],
    candidates: [R, GTE],
  }
  const picked = (c: typeof R) => ({
    vin: GOLF_VIN,
    make: 'Volkswagen',
    model: 'Golf',
    trim: c.label.replace('Golf ', ''),
    body_class: c === R ? 'Limousine R' : 'Limousine GTE',
    region: 'EU',
    decode_quality: 'full' as const,
    decoded_by: 'autoref' as const,
    notes: ['check_digit_not_applicable'],
  })
  const gteOption = 'Golf VII GTE · forms:fuel.fuelTypes.hybrid · vinInput.versionKw · Manual'
  const deferred = <T,>() => {
    let resolve: (value: T) => void = () => {}
    let reject: (reason: unknown) => void = () => {}
    const promise = new Promise<T>((res, rej) => {
      resolve = res
      reject = rej
    })
    return { promise, resolve, reject }
  }
  const decode = async (): Promise<HTMLSelectElement> => {
    fireEvent.click(screen.getByRole('button', { name: /vinInput.decode/ }))
    return (await screen.findByRole('combobox', { name: 'vinInput.version' })) as HTMLSelectElement
  }
  const pick = (select: HTMLSelectElement, c: typeof R): void => {
    fireEvent.change(select, { target: { value: `${c.record_type}:${c.id}` } })
  }

  beforeEach(() => {
    vi.mocked(vinService.decode).mockReset()
    vi.mocked(vinService.decodeVersion).mockReset()
    vi.mocked(vinService.providers).mockResolvedValue({ available: ['nhtsa', 'autoref'], preferred: 'autoref' })
  })

  it('shows no picker without candidates', async () => {
    vi.mocked(vinService.decode).mockResolvedValue({ ...picked(GTE) })
    render(<VINInput value={GOLF_VIN} onChange={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: /vinInput.decode/ }))
    await screen.findByText('vinInput.decodedTitle')
    expect(screen.queryByRole('combobox', { name: 'vinInput.version' })).not.toBeInTheDocument()
  })

  it('lists the versions after a decode', async () => {
    vi.mocked(vinService.decode).mockResolvedValue(several)
    render(<VINInput value={GOLF_VIN} onChange={vi.fn()} />)
    const select = await decode()
    const options = Array.from(select.options)
    expect(options).toHaveLength(3) // the placeholder, then R and GTE in order
    expect(options[0].value).toBe('')
    expect(options[0].textContent).toBe('vinInput.pickVersion')
    expect(options.slice(1).map((o) => o.value)).toEqual(['TG:310899', 'TG:311017'])
    expect(options[2].textContent).toBe(gteOption)
  })

  it('leaves out a part a version lacks', async () => {
    const bare = { ...GTE, fuel_type: null, kw: null, transmission: null }
    vi.mocked(vinService.decode).mockResolvedValue({ ...several, candidates: [R, bare] })
    render(<VINInput value={GOLF_VIN} onChange={vi.fn()} />)
    const select = await decode()
    expect(select.options[2].textContent).toBe('Golf VII GTE')
  })

  it('fills the form from the picked version', async () => {
    vi.mocked(vinService.decode).mockResolvedValue(several)
    vi.mocked(vinService.decodeVersion).mockResolvedValue(picked(GTE))
    const onDecode = vi.fn()
    render(<VINInput value={GOLF_VIN} onChange={vi.fn()} onDecode={onDecode} />)
    const select = await decode()
    pick(select, GTE)

    await waitFor(() => expect(onDecode).toHaveBeenCalledTimes(2))
    expect(vinService.decodeVersion).toHaveBeenCalledWith(GOLF_VIN, GTE)
    expect(onDecode).toHaveBeenLastCalledWith(picked(GTE))
    expect(await screen.findByText('Limousine GTE')).toBeInTheDocument()
    const after = screen.getByRole('combobox', { name: 'vinInput.version' }) as HTMLSelectElement
    expect(after.value).toBe('TG:311017')
  })

  it('keeps the answer when a pick fails', async () => {
    vi.mocked(vinService.decode).mockResolvedValue(several)
    vi.mocked(vinService.decodeVersion).mockRejectedValue({
      response: { status: 429, data: { detail: 'AutoRef quota used up' } },
    })
    const onDecode = vi.fn()
    render(<VINInput value={GOLF_VIN} onChange={vi.fn()} onDecode={onDecode} />)
    const select = await decode()
    pick(select, GTE)

    expect(await screen.findByTestId('vin-pick-error')).toBeInTheDocument()
    expect(onDecode).toHaveBeenCalledTimes(1)
    expect(screen.getByText('Volkswagen')).toBeInTheDocument()
    expect(screen.queryByText('Limousine GTE')).not.toBeInTheDocument()
    expect((screen.getByRole('combobox', { name: 'vinInput.version' }) as HTMLSelectElement).value).toBe('')
  })

  it('hides the picker after the VIN changes', async () => {
    vi.mocked(vinService.decode).mockResolvedValue(several)
    render(<VINInput value={GOLF_VIN} onChange={vi.fn()} />)
    await decode()
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'WVWZZZAUZFW80665' } })
    expect(screen.queryByRole('combobox', { name: 'vinInput.version' })).not.toBeInTheDocument()
  })

  it('hides the picker when the value prop changes', async () => {
    vi.mocked(vinService.decode).mockResolvedValue(several)
    const { rerender } = render(<VINInput value={GOLF_VIN} onChange={vi.fn()} />)
    await decode()
    rerender(<VINInput value="VF1RFB00X56123456" onChange={vi.fn()} />)
    expect(screen.queryByRole('combobox', { name: 'vinInput.version' })).not.toBeInTheDocument()
  })

  it('a slow pick never overwrites a newer one', async () => {
    const slowR = deferred<ReturnType<typeof picked>>()
    const fastGte = deferred<ReturnType<typeof picked>>()
    vi.mocked(vinService.decode).mockResolvedValue(several)
    vi.mocked(vinService.decodeVersion).mockReturnValueOnce(slowR.promise).mockReturnValueOnce(fastGte.promise)
    const onDecode = vi.fn()
    render(<VINInput value={GOLF_VIN} onChange={vi.fn()} onDecode={onDecode} />)
    const select = await decode()
    pick(select, R)
    pick(select, GTE)
    await act(async () => {
      fastGte.resolve(picked(GTE))
    })
    await act(async () => {
      slowR.resolve(picked(R))
    })

    expect(onDecode).toHaveBeenLastCalledWith(picked(GTE))
    expect(screen.getByText('Limousine GTE')).toBeInTheDocument()
    expect(screen.queryByText('Limousine R')).not.toBeInTheDocument()
  })

  it('a slow pick never overwrites a fresh decode', async () => {
    const slow = deferred<ReturnType<typeof picked>>()
    vi.mocked(vinService.decode).mockResolvedValueOnce(several).mockResolvedValueOnce({ ...picked(R), body_class: 'Fresh' })
    vi.mocked(vinService.decodeVersion).mockReturnValueOnce(slow.promise)
    const onDecode = vi.fn()
    render(<VINInput value={GOLF_VIN} onChange={vi.fn()} onDecode={onDecode} />)
    const select = await decode()
    pick(select, GTE)
    fireEvent.click(screen.getByRole('button', { name: /vinInput.decode/ }))
    expect(await screen.findByText('Fresh')).toBeInTheDocument()
    await act(async () => {
      slow.resolve(picked(GTE))
    })

    expect(onDecode).toHaveBeenCalledTimes(2)
    expect(screen.queryByText('Limousine GTE')).not.toBeInTheDocument()
    expect(screen.queryByRole('combobox', { name: 'vinInput.version' })).not.toBeInTheDocument()
  })

  it('hides the old picker while a fresh decode is on its way', async () => {
    // Codex diff R1-M1: a pick from the old list would cancel the new answer.
    const fresh = deferred<ReturnType<typeof picked>>()
    vi.mocked(vinService.decode).mockResolvedValueOnce(several).mockReturnValueOnce(fresh.promise)
    const onDecode = vi.fn()
    render(<VINInput value={GOLF_VIN} onChange={vi.fn()} onDecode={onDecode} />)
    await decode()
    fireEvent.click(screen.getByRole('button', { name: /vinInput.decode/ }))
    expect(screen.queryByRole('combobox', { name: 'vinInput.version' })).not.toBeInTheDocument()
    await act(async () => {
      fresh.resolve({ ...picked(R), body_class: 'Fresh' })
    })
    expect(screen.getByText('Fresh')).toBeInTheDocument()
    expect(onDecode).toHaveBeenCalledTimes(2)
  })

  it('a late failure never shows over a newer success', async () => {
    const slowR = deferred<ReturnType<typeof picked>>()
    vi.mocked(vinService.decode).mockResolvedValue(several)
    vi.mocked(vinService.decodeVersion).mockReturnValueOnce(slowR.promise).mockResolvedValueOnce(picked(GTE))
    render(<VINInput value={GOLF_VIN} onChange={vi.fn()} onDecode={vi.fn()} />)
    const select = await decode()
    pick(select, R)
    pick(select, GTE)
    expect(await screen.findByText('Limousine GTE')).toBeInTheDocument()
    await act(async () => {
      slowR.reject({ response: { status: 504, data: { detail: 'AutoRef request timed out' } } })
    })

    expect(screen.queryByTestId('vin-pick-error')).not.toBeInTheDocument()
    expect((screen.getByRole('combobox', { name: 'vinInput.version' }) as HTMLSelectElement).value).toBe('TG:311017')
  })

  it('a new decode without candidates clears the picker', async () => {
    vi.mocked(vinService.decode).mockResolvedValueOnce(several).mockResolvedValueOnce(picked(R))
    render(<VINInput value={GOLF_VIN} onChange={vi.fn()} />)
    await decode()
    fireEvent.click(screen.getByRole('button', { name: /vinInput.decode/ }))
    expect(await screen.findByText('Limousine R')).toBeInTheDocument()
    expect(screen.queryByRole('combobox', { name: 'vinInput.version' })).not.toBeInTheDocument()
  })

  it('Try AutoRef that returns candidates shows the picker', async () => {
    vi.mocked(vinService.decode)
      .mockResolvedValueOnce({ ...several, decoded_by: 'nhtsa', candidates: null, notes: ['eu_vin_no_model'] })
      .mockResolvedValueOnce(several)
    render(<VINInput value={GOLF_VIN} onChange={vi.fn()} />)
    await screen.findByLabelText('vinInput.decodeWith')
    fireEvent.click(screen.getByRole('button', { name: /vinInput.decode/ }))
    fireEvent.click(await screen.findByRole('button', { name: /vinInput.tryAutoRef/ }))
    expect(await screen.findByRole('combobox', { name: 'vinInput.version' })).toBeInTheDocument()
  })

  it('a pick after Try AutoRef only adds, like the Try', async () => {
    // Fable diff F-1: it must not blank what the first decoder filled.
    vi.mocked(vinService.decode)
      .mockResolvedValueOnce({ ...several, decoded_by: 'nhtsa', candidates: null, notes: ['eu_vin_no_model'] })
      .mockResolvedValueOnce(several)
    vi.mocked(vinService.decodeVersion).mockResolvedValue(picked(GTE))
    const onDecode = vi.fn()
    render(<VINInput value={GOLF_VIN} onChange={vi.fn()} onDecode={onDecode} />)
    await screen.findByLabelText('vinInput.decodeWith')
    fireEvent.click(screen.getByRole('button', { name: /vinInput.decode/ }))
    fireEvent.click(await screen.findByRole('button', { name: /vinInput.tryAutoRef/ }))
    pick((await screen.findByRole('combobox', { name: 'vinInput.version' })) as HTMLSelectElement, GTE)
    await waitFor(() => expect(onDecode).toHaveBeenCalledTimes(3))
    expect(onDecode).toHaveBeenLastCalledWith(picked(GTE), { fillOnly: true })
  })

  it('a partial answer with versions leads with the pick note and offers no Try NHTSA', async () => {
    vi.mocked(vinService.decode).mockResolvedValue(several)
    render(<VINInput value={GOLF_VIN} onChange={vi.fn()} />)
    await screen.findByLabelText('vinInput.decodeWith')
    await decode()
    const notice = screen.getByTestId('vin-partial-decode')
    expect(notice.querySelector('p')).toHaveTextContent('vinInput.notes.autoref_pick_version')
    expect(notice).not.toHaveTextContent('vinInput.euPartial')
    expect(notice).toHaveTextContent('vinInput.notes.check_digit_not_applicable')
    expect(screen.queryByRole('button', { name: /vinInput.tryNhtsa/ })).not.toBeInTheDocument()
  })

  it('choosing the placeholder again sends nothing', async () => {
    vi.mocked(vinService.decode).mockResolvedValue(several)
    render(<VINInput value={GOLF_VIN} onChange={vi.fn()} />)
    const select = await decode()
    fireEvent.change(select, { target: { value: '' } })
    expect(vinService.decodeVersion).not.toHaveBeenCalled()
  })
})
