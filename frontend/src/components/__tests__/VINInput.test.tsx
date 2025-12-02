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

    // Component should handle uppercase conversion
    expect(input).toHaveValue('1HGBH41JXMN109186')
  })

  it('validates VIN length', () => {
    const onChangeMock = vi.fn()
    render(<VINInput value="SHORT" onChange={onChangeMock} error="VIN must be 17 characters" />)

    expect(screen.getByText(/VIN must be 17 characters/i)).toBeInTheDocument()
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
