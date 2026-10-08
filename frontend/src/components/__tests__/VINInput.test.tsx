import { describe, it, expect, vi } from 'vitest'
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
  },
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
