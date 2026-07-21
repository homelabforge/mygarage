import { describe, it, expect, vi } from 'vitest'
import { Wrench } from 'lucide-react'
import { render, screen, fireEvent } from '../../../__tests__/test-utils'
import ListRow from '../ListRow'
import type { IconType } from '../types'

describe('ListRow', () => {
  it('renders label and value', () => {
    render(<ListRow label="Last Service" value="Jun 19, 2026" />)
    expect(screen.getByText('Last Service')).toBeInTheDocument()
    expect(screen.getByText('Jun 19, 2026')).toBeInTheDocument()
  })

  it('renders the value in mono by default', () => {
    render(<ListRow label="Latest Odometer" value="89,230 mi" />)
    expect(screen.getByText('89,230 mi')).toHaveClass('font-mono')
  })

  it('can opt the value out of mono', () => {
    render(<ListRow label="Type" value="Truck" mono={false} />)
    expect(screen.getByText('Truck')).not.toHaveClass('font-mono')
  })

  it('renders a real button when clickable', () => {
    const onClick = vi.fn()
    render(<ListRow label="Docs" value="2" onClick={onClick} />)
    fireEvent.click(screen.getByRole('button'))
    expect(onClick).toHaveBeenCalledOnce()
  })

  it('carries a stable test id', () => {
    render(<ListRow icon={Wrench} label="Fuel" value="29" />)
    expect(screen.getByTestId('list-row')).toBeInTheDocument()
  })

  it('marks the icon aria-hidden itself, not just relying on the icon default', () => {
    // lucide-react icons default to aria-hidden="true" whenever no other
    // a11y prop is passed, so a test using a real lucide icon (like Wrench
    // above) can't tell whether ListRow sets the attribute itself or is only
    // inheriting lucide's default. A bare SVG component has no such default,
    // so this proves ListRow supplies the attribute itself rather than
    // relying on it.
    const BareIcon: IconType = (props) => <svg data-testid="bare-icon" {...props} />
    render(<ListRow icon={BareIcon} label="Last Service" value="Jun 19, 2026" />)
    expect(screen.getByTestId('bare-icon')).toHaveAttribute('aria-hidden', 'true')
  })

  it('renders a trailing node alongside the value', () => {
    render(
      <ListRow
        label="Warranty"
        value="Active"
        trailing={<span data-testid="trailing-node">New</span>}
      />,
    )
    expect(screen.getByTestId('trailing-node')).toBeInTheDocument()
  })
})
