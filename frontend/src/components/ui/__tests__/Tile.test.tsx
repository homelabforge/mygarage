import { describe, it, expect } from 'vitest'
import { Wrench } from 'lucide-react'
import { render, screen } from '../../../__tests__/test-utils'
import Tile from '../Tile'
import type { IconType } from '../types'

describe('Tile', () => {
  it('renders label and value', () => {
    render(<Tile icon={Wrench} label="Service" value={10} />)
    expect(screen.getByText('Service')).toBeInTheDocument()
    expect(screen.getByText('10')).toBeInTheDocument()
  })

  it('renders the value in mono so tiles align in a row', () => {
    render(<Tile icon={Wrench} label="Service" value={10} />)
    expect(screen.getByText('10')).toHaveClass('font-mono')
  })

  it('accepts a non-numeric value', () => {
    render(<Tile icon={Wrench} label="Spent 2026" value="$1,284.00" />)
    expect(screen.getByText('$1,284.00')).toBeInTheDocument()
  })

  it('tones the value for danger without touching the label', () => {
    render(<Tile icon={Wrench} label="Overdue" value={2} tone="danger" />)
    expect(screen.getByText('2')).toHaveClass('text-danger')
    expect(screen.getByText('Overdue')).not.toHaveClass('text-danger')
  })

  it('marks the icon aria-hidden itself, not just relying on the icon default', () => {
    // lucide-react icons default to aria-hidden="true" whenever no other
    // a11y prop is passed (dist/cjs/lucide-react.js:
    // `...!children && !hasA11yProp(rest) && { 'aria-hidden': 'true' }`), so
    // a test using a lucide icon (e.g. Wrench above) can't tell whether Tile
    // sets the attribute itself or is only inheriting lucide's default. A
    // bare SVG component has no such default, so this proves Tile supplies
    // the attribute itself rather than relying on it.
    const BareIcon: IconType = (props) => <svg data-testid="bare-icon" {...props} />
    render(<Tile icon={BareIcon} label="Service" value={1} />)
    expect(screen.getByTestId('bare-icon')).toHaveAttribute('aria-hidden', 'true')
  })
})
