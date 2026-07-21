import { describe, it, expect, vi } from 'vitest'
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

  it('marks the icon aria-hidden itself, not just relying on the icon default', () => {
    // lucide-react icons default to aria-hidden="true" whenever no other
    // a11y prop is passed (dist/cjs/lucide-react.js:
    // `...!children && !hasA11yProp(rest) && { 'aria-hidden': 'true' }`), so
    // a test using a real lucide icon can't tell whether Chip sets the
    // attribute itself or is only inheriting lucide's default. A
    // bare SVG component has no such default, so this proves Chip supplies
    // the attribute itself rather than relying on it.
    const BareIcon: IconType = (props) => <svg data-testid="bare-icon" {...props} />
    render(<Chip icon={BareIcon}>Service</Chip>)
    expect(screen.getByTestId('bare-icon')).toHaveAttribute('aria-hidden', 'true')
  })

  // jsdom renders no CSS, so these can only assert on the class string, not
  // on an actual computed border-color — they cannot see that `ui-hover-line`
  // (index.css) hardcodes border-color: var(--accent-line). But they do
  // genuinely discriminate against the regression: the prior implementation
  // applied `ui-hover-line` unconditionally on the interactive branch, so a
  // toned chip's button carried it and never carried a `hover:bg-{tone}/25`
  // class. Each case below fails against that prior code (present
  // ui-hover-line, absent hover:bg-*/25) and passes only once a fixed-status
  // tone gets its own-colour hover instead of the accent-derived one.
  it.each([
    ['success', 'hover:bg-success/25'],
    ['warning', 'hover:bg-warning/25'],
    ['danger', 'hover:bg-danger/25'],
    ['info', 'hover:bg-info/25'],
  ] as const)('keeps a %s interactive chip on its own colour on hover, not the accent border', (tone, hoverClass) => {
    render(<Chip onClick={() => {}} tone={tone}>Status</Chip>)
    const button = screen.getByRole('button', { name: 'Status' })
    expect(button.className).toContain(hoverClass)
    expect(button.className).not.toMatch(/\bui-hover-line\b/)
  })

  it('still uses the shared accent-line hover for default, muted and accent tones', () => {
    for (const tone of ['default', 'muted', 'accent'] as const) {
      render(<Chip onClick={() => {}} tone={tone}>{tone}</Chip>)
      expect(screen.getByRole('button', { name: tone }).className).toMatch(/\bui-hover-line\b/)
    }
  })
})
