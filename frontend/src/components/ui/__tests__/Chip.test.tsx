import { describe, it, expect, vi } from 'vitest'
import { Wrench } from 'lucide-react'
import { render, screen, fireEvent } from '../../../__tests__/test-utils'
import Chip from '../Chip'

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
})
