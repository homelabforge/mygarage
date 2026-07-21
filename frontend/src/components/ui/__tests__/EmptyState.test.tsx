import { describe, it, expect } from 'vitest'
import { Box } from 'lucide-react'
import { render, screen } from '../../../__tests__/test-utils'
import EmptyState from '../EmptyState'

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

  it('hides the decorative icon from assistive tech', () => {
    const { container } = render(<EmptyState icon={Box} title="Empty" />)
    expect(container.querySelector('svg')).toHaveAttribute('aria-hidden', 'true')
  })
})
