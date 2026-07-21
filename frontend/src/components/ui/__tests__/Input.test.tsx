import { describe, it, expect } from 'vitest'
import { render, screen } from '../../../__tests__/test-utils'
import Input from '../Input'
import Textarea from '../Textarea'

describe('Input', () => {
  it('forwards id, name and placeholder verbatim', () => {
    // e2e pins #odometer_km and input[name="nickname"]; unit tests pin
    // placeholders at Login.test.tsx and elsewhere (G6).
    render(<Input id="odometer_km" name="odometer_km" placeholder="0" />)
    const input = screen.getByPlaceholderText('0')
    expect(input).toHaveAttribute('id', 'odometer_km')
    expect(input).toHaveAttribute('name', 'odometer_km')
  })

  it('keeps the spinbutton role for numeric inputs', () => {
    render(<Input type="number" aria-label="Quantity" />)
    expect(screen.getByRole('spinbutton', { name: 'Quantity' })).toBeInTheDocument()
  })

  it('keeps the textbox role for text inputs', () => {
    render(<Input type="text" aria-label="VIN" />)
    const input = screen.getByRole('textbox', { name: 'VIN' })
    expect(input).toBeInTheDocument()
    expect(input).toHaveAttribute('type', 'text')
  })

  it('applies the mono family when asked', () => {
    render(<Input mono aria-label="Cost" />)
    expect(screen.getByRole('textbox', { name: 'Cost' })).toHaveClass('font-mono')
  })

  it('marks invalid state for assistive tech', () => {
    render(<Input invalid aria-label="Cost" />)
    expect(screen.getByRole('textbox', { name: 'Cost' })).toHaveAttribute('aria-invalid', 'true')
  })

  it('renders a prefix before the control', () => {
    const { container } = render(<Input prefix="$" aria-label="Cost" />)
    expect(container.querySelector('span')).toHaveTextContent('$')
  })

  it('renders a suffix after the control', () => {
    const { container } = render(<Input suffix="kg" aria-label="Weight" />)
    expect(container.querySelector('span')).toHaveTextContent('kg')
    expect(screen.getByRole('textbox', { name: 'Weight' })).toHaveClass('pr-7')
  })
})

describe('Textarea', () => {
  it('renders a real textarea and forwards id', () => {
    render(<Textarea id="notes" aria-label="Notes" />)
    expect(screen.getByRole('textbox', { name: 'Notes' }).tagName).toBe('TEXTAREA')
  })
})
