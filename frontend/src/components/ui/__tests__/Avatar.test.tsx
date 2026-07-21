import { describe, it, expect } from 'vitest'
import { render, screen } from '../../../__tests__/test-utils'
import Avatar from '../Avatar'

describe('Avatar', () => {
  it('derives initials from a single name', () => {
    render(<Avatar name="Jamey" />)
    expect(screen.getByText('J')).toBeInTheDocument()
  })

  it('derives two initials from a full name', () => {
    render(<Avatar name="Jamey Starett" />)
    expect(screen.getByText('JS')).toBeInTheDocument()
  })

  it('exposes the name to assistive tech, not the initials', () => {
    render(<Avatar name="Jamey Starett" />)
    expect(screen.getByLabelText('Jamey Starett')).toBeInTheDocument()
  })

  it('renders an image when given one', () => {
    render(<Avatar name="Jamey" src="/photo.jpg" />)
    expect(screen.getByRole('img')).toHaveAttribute('src', '/photo.jpg')
  })

  it('tolerates an empty name without crashing', () => {
    const { container } = render(<Avatar name="" />)
    expect(container.firstChild).toBeInTheDocument()
  })
})
