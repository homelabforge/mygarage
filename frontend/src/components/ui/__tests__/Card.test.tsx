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
  it('renders title alongside the icon element', () => {
    // This only proves CardHeader renders an icon element next to the title —
    // not that CardHeader sets aria-hidden itself. lucide-react icons
    // (Wrench above) default to aria-hidden="true" on their own, so an
    // assertion on that attribute here would pass identically whether or not
    // CardHeader sets it; see the bare-icon test below for that contract.
    const { container } = render(<CardHeader title="Cost by Category" icon={Wrench} />)
    expect(screen.getByRole('heading', { name: 'Cost by Category' })).toBeInTheDocument()
    expect(container.querySelector('svg')).toBeInTheDocument()
  })

  it('marks the icon aria-hidden itself, not just relying on the icon default', () => {
    // lucide-react icons default to aria-hidden="true" whenever no other
    // a11y prop is passed (dist/cjs/lucide-react.js:
    // `...!children && !hasA11yProp(rest) && { 'aria-hidden': 'true' }`), so
    // a test using a lucide icon (e.g. Wrench above) can't tell whether
    // CardHeader sets the attribute itself or is only inheriting lucide's
    // default. A bare SVG component has no such default, so this proves
    // CardHeader supplies the attribute itself rather than relying on it.
    const BareIcon: IconType = (props) => <svg data-testid="bare-icon" {...props} />
    render(<CardHeader title="X" icon={BareIcon} />)
    expect(screen.getByTestId('bare-icon')).toHaveAttribute('aria-hidden', 'true')
  })
})
