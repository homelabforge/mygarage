import { describe, it, expect } from 'vitest'
import { Box } from 'lucide-react'
import { render, screen } from '../../../__tests__/test-utils'
import EmptyState from '../EmptyState'
import type { IconType } from '../types'

describe('EmptyState', () => {
  it('renders title and description', () => {
    render(<EmptyState icon={Box} title="No supplies yet" description="Add your first one." />)
    expect(screen.getByRole('heading', { name: 'No supplies yet' })).toBeInTheDocument()
    expect(screen.getByText('Add your first one.')).toBeInTheDocument()
  })

  it('renders an action when given one', () => {
    render(
      <EmptyState icon={Box} title="Empty" action={<button>Add Supply</button>} />,
    )
    expect(screen.getByRole('button', { name: 'Add Supply' })).toBeInTheDocument()
  })

  it('marks the icon aria-hidden itself, not just relying on the icon default', () => {
    // lucide-react icons default to aria-hidden="true" whenever no other
    // a11y prop is passed (dist/cjs/lucide-react.js:
    // `...!children && !hasA11yProp(rest) && { 'aria-hidden': 'true' }`), so
    // a test using a lucide icon (e.g. Box above) can't tell whether
    // EmptyState sets the attribute itself or is only inheriting lucide's
    // default. A bare SVG component has no such default, so this proves
    // EmptyState supplies the attribute itself rather than relying on it.
    // This is not theoretical here: the heading carries the meaning and the
    // icon is purely decorative, so a screen-reader user genuinely depends
    // on EmptyState setting this itself.
    const BareIcon: IconType = (props) => <svg data-testid="bare-icon" {...props} />
    render(<EmptyState icon={BareIcon} title="Empty" />)
    expect(screen.getByTestId('bare-icon')).toHaveAttribute('aria-hidden', 'true')
  })
})
