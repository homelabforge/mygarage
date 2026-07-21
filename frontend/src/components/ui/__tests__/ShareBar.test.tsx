import { describe, it, expect } from 'vitest'
import { render, screen } from '../../../__tests__/test-utils'
import ShareBar from '../ShareBar'

describe('ShareBar', () => {
  it('renders label, value and percentage', () => {
    render(<ShareBar label="Maintenance" value="$1,284.00" percent={42} color="#f0a53a" />)
    expect(screen.getByText('Maintenance')).toBeInTheDocument()
    expect(screen.getByText('$1,284.00')).toBeInTheDocument()
    expect(screen.getByText('42%')).toBeInTheDocument()
  })

  it('exposes the share as a progressbar', () => {
    render(<ShareBar label="Maintenance" value="$1,284.00" percent={42} color="#f0a53a" />)
    const bar = screen.getByRole('progressbar', { name: 'Maintenance' })
    expect(bar).toHaveAttribute('aria-valuenow', '42')
  })

  it('clamps out-of-range percentages', () => {
    render(<ShareBar label="Over" value="x" percent={140} color="#f0a53a" />)
    expect(screen.getByRole('progressbar', { name: 'Over' })).toHaveAttribute('aria-valuenow', '100')
  })

  it('clamps negative percentages to zero', () => {
    // The brief's own test only exercises the upper bound; task note 3
    // requires both directions ("above 100 or below 0"), and the clamp
    // implementation (Math.max(0, ...)) has a lower bound that nothing above
    // would exercise.
    render(<ShareBar label="Under" value="x" percent={-15} color="#f0a53a" />)
    expect(screen.getByRole('progressbar', { name: 'Under' })).toHaveAttribute('aria-valuenow', '0')
  })

  it('renders figures in mono', () => {
    render(<ShareBar label="Maintenance" value="$1,284.00" percent={42} color="#f0a53a" />)
    expect(screen.getByText('$1,284.00')).toHaveClass('font-mono')
  })
})
