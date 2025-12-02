import { describe, it, expect } from 'vitest'
import { render, screen } from '../../__tests__/test-utils'
import { FormError } from '../FormError'

describe('FormError', () => {
  it('renders error message', () => {
    render(<FormError error={{ message: "This field is required" }} />)

    expect(screen.getByText(/This field is required/i)).toBeInTheDocument()
  })

  it('does not render when no message', () => {
    const { container } = render(<FormError error={undefined} />)

    expect(container.firstChild).toBeNull()
  })

  it('applies error styling', () => {
    const { container } = render(<FormError error={{ message: "Error" }} />)

    const errorElement = container.firstChild
    expect(errorElement).toHaveClass('text-red-500')
  })

  it('handles long error messages', () => {
    const longMessage = 'This is a very long error message that should still be displayed properly'
    render(<FormError error={{ message: longMessage }} />)

    expect(screen.getByText(longMessage)).toBeInTheDocument()
  })
})
