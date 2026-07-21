import { describe, it, expect } from 'vitest'
import { render, screen } from '../../../__tests__/test-utils'
import PageContainer from '../PageContainer'

describe('PageContainer', () => {
  it('renders its children', () => {
    render(<PageContainer><p>content</p></PageContainer>)
    expect(screen.getByText('content')).toBeInTheDocument()
  })

  it('uses the prototype measure, not Tailwind container', () => {
    const { container } = render(<PageContainer>x</PageContainer>)
    const el = container.firstChild as HTMLElement
    expect(el).toHaveClass('max-w-[1320px]')
    // `container` steps at breakpoints and would give a different width at
    // every viewport than the design specifies.
    expect(el).not.toHaveClass('container')
  })
})
