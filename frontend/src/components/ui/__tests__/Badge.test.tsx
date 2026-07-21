import { describe, it, expect } from 'vitest'
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

  it("does not force a toned badge's count digit to text-text, so it can inherit the badge's own foreground", () => {
    // tone="danger" sets bg-danger text-on-status on the badge span. If the
    // count digit (a Mono) applies its own default 'text-text' on top, the
    // digit ignores --color-on-status and falls back to the page foreground
    // instead of the contrast colour the tone map chose for this fill.
    render(<Badge tone="danger" count={2} />)
    const digit = screen.getByText('2')
    expect(digit).not.toHaveClass('text-text')
  })

  it('marks the icon aria-hidden itself, not just relying on the icon default', () => {
    // lucide-react icons default to aria-hidden="true" whenever no other
    // a11y prop is passed (dist/cjs/lucide-react.js:
    // `...!children && !hasA11yProp(rest) && { 'aria-hidden': 'true' }`), so
    // a test using a real lucide icon can't tell whether Badge sets the
    // attribute itself or is only inheriting lucide's default. A
    // bare SVG component has no such default, so this proves Badge supplies
    // the attribute itself rather than relying on it.
    const BareIcon: IconType = (props) => <svg data-testid="bare-icon" {...props} />
    render(<Badge icon={BareIcon}>Service</Badge>)
    expect(screen.getByTestId('bare-icon')).toHaveAttribute('aria-hidden', 'true')
  })
})
