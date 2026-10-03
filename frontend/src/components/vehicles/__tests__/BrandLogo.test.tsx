import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import BrandLogo from '../BrandLogo'

describe('BrandLogo', () => {
  it('renders brand logo img for known make', () => {
    render(<BrandLogo make="Ford" />)
    const img = screen.getByRole('img')
    expect(img).toHaveAttribute('src', expect.stringContaining('ford.png'))
    expect(img).toHaveAttribute('alt', 'Ford')
  })

  it('renders fallback icon when brand has no logo', () => {
    const { container } = render(<BrandLogo make="UnknownMake123" />)
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
    expect(container.querySelector('svg')).toBeInTheDocument()
  })

  it('falls back to icon on image error', () => {
    const { container } = render(<BrandLogo make="Ford" />)
    const img = screen.getByRole('img')
    fireEvent.error(img)
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
    expect(container.querySelector('svg')).toBeInTheDocument()
  })

  it('resets error state when make changes', () => {
    const { rerender } = render(<BrandLogo make="Ford" />)
    const img = screen.getByRole('img')
    fireEvent.error(img)
    expect(screen.queryByRole('img')).not.toBeInTheDocument()

    rerender(<BrandLogo make="Toyota" />)
    const newImg = screen.getByRole('img')
    expect(newImg).toHaveAttribute('src', expect.stringContaining('toyota.png'))
  })
})
