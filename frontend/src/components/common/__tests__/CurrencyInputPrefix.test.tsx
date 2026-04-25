import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '../../../__tests__/test-utils'
import CurrencyInputPrefix from '../CurrencyInputPrefix'

vi.mock('../../../hooks/useCurrencyPreference', () => ({
  useCurrencyPreference: () => ({
    currencyCode: 'EUR',
    locale: 'de-DE',
    formatCurrency: () => '€0,00',
  }),
}))

describe('CurrencyInputPrefix', () => {
  it('renders the currency symbol for the user preference', () => {
    render(<CurrencyInputPrefix />)
    expect(screen.getByText('€')).toBeInTheDocument()
  })

  it('applies the default positioning classes when no className is given', () => {
    const { container } = render(<CurrencyInputPrefix />)
    const span = container.querySelector('span')
    expect(span).toHaveClass('absolute')
    expect(span).toHaveClass('left-3')
    expect(span).toHaveClass('top-2')
  })

  it('respects a custom className override', () => {
    const { container } = render(<CurrencyInputPrefix className="custom-class" />)
    const span = container.querySelector('span')
    expect(span).toHaveClass('custom-class')
    // default positioning is NOT applied when overridden
    expect(span).not.toHaveClass('top-2')
  })

  it('is marked aria-hidden', () => {
    const { container } = render(<CurrencyInputPrefix />)
    const span = container.querySelector('span')
    expect(span).toHaveAttribute('aria-hidden', 'true')
  })
})
