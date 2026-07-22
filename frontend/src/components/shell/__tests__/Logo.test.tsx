import { describe, it, expect } from 'vitest'
import { render, screen } from '../../../__tests__/test-utils'
import Logo from '../Logo'

describe('Logo', () => {
  it('links to / with the MyGarage accessible name', () => {
    render(<Logo />)
    const link = screen.getByRole('link', { name: 'MyGarage' })
    expect(link).toHaveAttribute('href', '/')
  })

  it('renders the two-tone wordmark with an accent "My"', () => {
    render(<Logo />)
    const my = screen.getByText('My')
    expect(my).toHaveClass('text-(--accent)')
  })

  it('hides the brand mark from assistive tech', () => {
    const { container } = render(<Logo />)
    const svg = container.querySelector('svg')
    expect(svg).toHaveAttribute('aria-hidden', 'true')
  })
})
