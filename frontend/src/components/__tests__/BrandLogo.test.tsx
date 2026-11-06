import { describe, expect, it } from 'vitest'
import { fireEvent, render } from '@testing-library/react'
import BrandLogo from '../BrandLogo'

describe('BrandLogo', () => {
  it('shows the next make\'s logo after one failed to load', () => {
    // Fable diff F-5: a failure belongs to that file, not to the component.
    const { container, rerender } = render(<BrandLogo slug="audi" name="Audi" />)
    fireEvent.error(container.querySelector('img') as HTMLImageElement)
    expect(container.querySelector('img')).toBeNull()
    expect(container).toHaveTextContent('A')

    rerender(<BrandLogo slug="bmw" name="BMW" />)
    expect(container.querySelector('img')).toHaveAttribute('src', expect.stringContaining('/brand-logos/bmw.png'))
  })
})
