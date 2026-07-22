import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import TopNavLink from '../TopNavLink'

function at(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/analytics" element={<TopNavLink to="/analytics" label="nav:analytics" variant="inline" />} />
        <Route path="/supplies" element={<TopNavLink to="/analytics" label="nav:analytics" variant="inline" />} />
      </Routes>
    </MemoryRouter>
  )
}

describe('TopNavLink (inline)', () => {
  it('marks the active link semibold with an aria-hidden accent underline', () => {
    at('/analytics')
    const link = screen.getByRole('link', { name: 'nav:analytics' })
    expect(link).toHaveClass('font-semibold', 'text-text')
    const underline = link.querySelector('span[aria-hidden="true"]')
    expect(underline).not.toBeNull()
    expect(underline).toHaveClass('bg-(--accent)')
  })

  it('renders the inactive link muted with no underline, name == label only', () => {
    at('/supplies')
    const link = screen.getByRole('link', { name: 'nav:analytics' })
    expect(link).toHaveClass('font-medium', 'text-text-mute')
    expect(link.querySelector('span[aria-hidden="true"]')).toBeNull()
  })
})
