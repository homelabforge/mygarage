import { describe, it, expect } from 'vitest'
import { Wrench } from 'lucide-react'
import { render, screen } from '../../../__tests__/test-utils'
import Badge from '../Badge'

describe('Badge', () => {
  it('renders its label', () => {
    render(<Badge>1 Upcoming</Badge>)
    expect(screen.getByText('1 Upcoming')).toBeInTheDocument()
  })

  it('renders a numeric count in mono', () => {
    render(<Badge count={3} />)
    expect(screen.getByText('3')).toHaveClass('font-mono')
  })

  it('uses token colours, never a raw palette', () => {
    const { container } = render(<Badge tone="danger">overdue</Badge>)
    expect(container.firstChild).toHaveClass('bg-danger')
    expect((container.firstChild as HTMLElement).className).not.toMatch(/-(red|amber)-\d/)
  })

  it('renders a decorative icon marked aria-hidden', () => {
    const { container } = render(<Badge icon={Wrench}>Service</Badge>)
    expect(container.querySelector('svg')).toHaveAttribute('aria-hidden', 'true')
  })
})
