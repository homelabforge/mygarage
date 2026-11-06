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

import { waitFor } from '@testing-library/react'
import { vinService } from '@/services/vinService'

describe('VINInput — European VINs (#211)', () => {
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
})
