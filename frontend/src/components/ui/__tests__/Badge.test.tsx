import { describe, it, expect } from 'vitest'
import { Wrench } from 'lucide-react'
import { render, screen } from '../../../__tests__/test-utils'
import Badge from '../Badge'
import type { IconType } from '../types'

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

  it('marks the icon aria-hidden itself, not just relying on the icon default', () => {
    // lucide-react icons (Wrench above) already default to aria-hidden="true"
    // whenever no other a11y prop is passed (dist/cjs/lucide-react.js:
    // `...!children && !hasA11yProp(rest) && { 'aria-hidden': 'true' }`), so
    // the assertion above passes identically whether or not Badge passes
    // aria-hidden itself. A bare SVG component has no such default, so this
    // proves Badge supplies the attribute rather than inheriting it.
    const BareIcon: IconType = (props) => <svg data-testid="bare-icon" {...props} />
    render(<Badge icon={BareIcon}>Service</Badge>)
    expect(screen.getByTestId('bare-icon')).toHaveAttribute('aria-hidden', 'true')
  })
})
