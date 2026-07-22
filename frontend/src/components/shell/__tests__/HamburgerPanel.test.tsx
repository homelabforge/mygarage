import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import HamburgerPanel from '../HamburgerPanel'

describe('HamburgerPanel', () => {
  it('re-shows the search field and stacks the six desktop-label links', () => {
    render(
      <MemoryRouter>
        <HamburgerPanel onNavigate={() => {}} />
      </MemoryRouter>
    )
    expect(screen.getByRole('button', { name: 'searchPlaceholder' })).toBeInTheDocument()
    for (const name of ['nav:dashboard', 'nav:analytics', 'nav:addressBook', 'nav:supplies', 'nav:findPOI', 'nav:calendar']) {
      expect(screen.getByRole('link', { name })).toBeInTheDocument()
    }
  })

  it('calls onNavigate when a link is clicked', () => {
    const onNavigate = vi.fn()
    render(
      <MemoryRouter>
        <HamburgerPanel onNavigate={onNavigate} />
      </MemoryRouter>
    )
    fireEvent.click(screen.getByRole('link', { name: 'nav:dashboard' }))
    expect(onNavigate).toHaveBeenCalledOnce()
  })
})
