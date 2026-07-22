import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import NavSearch from '../NavSearch'

describe('NavSearch (shelled)', () => {
  it('is a button, not a dead input', () => {
    const { container } = render(<NavSearch placeholder="search" />)
    expect(screen.getByRole('button', { name: 'search' })).toBeInTheDocument()
    expect(container.querySelector('input')).toBeNull()
  })

  it('opens a drawer with a coming-soon empty state', async () => {
    render(<NavSearch placeholder="search" />)
    fireEvent.click(screen.getByRole('button', { name: 'search' }))
    expect(await screen.findByRole('dialog', { name: 'search' })).toBeInTheDocument()
    expect(screen.getByText('searchShellTitle')).toBeInTheDocument()
    // still no real search field, even in the open panel
    expect(document.querySelector('input')).toBeNull()
  })

  it('forwards a band className onto the trigger', () => {
    render(<NavSearch placeholder="search" className="hidden nav:flex" />)
    expect(screen.getByRole('button', { name: 'search' })).toHaveClass('hidden', 'nav:flex')
  })
})
