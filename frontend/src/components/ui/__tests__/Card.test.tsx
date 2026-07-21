import { describe, it, expect, vi } from 'vitest'
import { Wrench } from 'lucide-react'
import { render, screen, fireEvent } from '../../../__tests__/test-utils'
import Card from '../Card'
import CardHeader from '../CardHeader'
import type { IconType } from '../types'

describe('Card', () => {
  it('renders children with the card surface', () => {
    const { container } = render(<Card>body</Card>)
    expect(container.firstChild).toHaveClass('bg-surface')
    expect(screen.getByText('body')).toBeInTheDocument()
  })

  it('renders a real button when interactive, so it is keyboard reachable', () => {
    const onClick = vi.fn()
    render(<Card interactive onClick={onClick}>clickable</Card>)
    const card = screen.getByRole('button')
    fireEvent.click(card)
    expect(onClick).toHaveBeenCalledOnce()
  })

  it('stays a plain div when not interactive', () => {
    const { container } = render(<Card>inert</Card>)
    expect(container.querySelector('button')).not.toBeInTheDocument()
  })
})

describe('CardHeader', () => {
  it('renders title and icon', () => {
    const { container } = render(<CardHeader title="Cost by Category" icon={Wrench} />)
    expect(screen.getByRole('heading', { name: 'Cost by Category' })).toBeInTheDocument()
    expect(container.querySelector('svg')).toHaveAttribute('aria-hidden', 'true')
  })

  it('marks the icon aria-hidden itself, not just relying on the icon default', () => {
    // lucide-react icons (Wrench above) already default to aria-hidden="true"
    // whenever no other a11y prop is passed (dist/cjs/lucide-react.js:
    // `...!children && !hasA11yProp(rest) && { 'aria-hidden': 'true' }`), so
    // the assertion above passes identically whether or not CardHeader passes
    // aria-hidden itself. A bare SVG component has no such default, so this
    // proves CardHeader supplies the attribute rather than inheriting it.
    const BareIcon: IconType = (props) => <svg data-testid="bare-icon" {...props} />
    render(<CardHeader title="X" icon={BareIcon} />)
    expect(screen.getByTestId('bare-icon')).toHaveAttribute('aria-hidden', 'true')
  })
})
