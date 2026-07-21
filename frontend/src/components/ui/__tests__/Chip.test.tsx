import { describe, it, expect, vi } from 'vitest'
import { Wrench } from 'lucide-react'
import { render, screen, fireEvent } from '../../../__tests__/test-utils'
import Chip from '../Chip'
import type { IconType } from '../types'

describe('Chip', () => {
  it('renders a span when it is not interactive', () => {
    const { container } = render(<Chip>Truck</Chip>)
    expect(container.querySelector('span')).toBeInTheDocument()
    expect(container.querySelector('button')).not.toBeInTheDocument()
  })

  it('renders a real button when given onClick', () => {
    const onClick = vi.fn()
    render(<Chip onClick={onClick}>Service</Chip>)
    const button = screen.getByRole('button', { name: 'Service' })
    fireEvent.click(button)
    expect(onClick).toHaveBeenCalledOnce()
  })

  it('exposes selection state to assistive tech', () => {
    render(<Chip onClick={() => {}} selected>Service</Chip>)
    expect(screen.getByRole('button', { name: 'Service' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('renders a decorative icon marked aria-hidden', () => {
    const { container } = render(<Chip icon={Wrench}>Service</Chip>)
    expect(container.querySelector('svg')).toHaveAttribute('aria-hidden', 'true')
  })

  it('marks the icon aria-hidden itself, not just relying on the icon default', () => {
    // lucide-react icons (Wrench above) already default to aria-hidden="true"
    // whenever no other a11y prop is passed (dist/cjs/lucide-react.js:
    // `...!children && !hasA11yProp(rest) && { 'aria-hidden': 'true' }`), so
    // the assertion above passes identically whether or not Chip passes
    // aria-hidden itself. A bare SVG component has no such default, so this
    // proves Chip supplies the attribute rather than inheriting it.
    const BareIcon: IconType = (props) => <svg data-testid="bare-icon" {...props} />
    render(<Chip icon={BareIcon}>Service</Chip>)
    expect(screen.getByTestId('bare-icon')).toHaveAttribute('aria-hidden', 'true')
  })
})
