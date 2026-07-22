import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import * as AuthContext from '../../contexts/AuthContext'
import Layout from '../Layout'

vi.mock('../../contexts/AuthContext')

function setup(initialPath = '/supplies') {
  vi.spyOn(AuthContext, 'useAuth').mockReturnValue({
    user: null,
    isAuthenticated: false,
    isAdmin: false,
    logout: vi.fn(),
  } as unknown as ReturnType<typeof AuthContext.useAuth>)

  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route path="supplies" element={<div>Supplies Page</div>} />
        </Route>
      </Routes>
    </MemoryRouter>
  )
}

describe('Layout supplies nav', () => {
  it('renders both nav links to /supplies', () => {
    setup()
    const links = screen
      .getAllByRole('link')
      .filter((l) => l.getAttribute('href') === '/supplies')
    expect(links).toHaveLength(2)
  })

  it('marks the mobile /supplies tab active on that route', () => {
    setup('/supplies')
    const links = screen
      .getAllByRole('link')
      .filter((l) => l.getAttribute('href') === '/supplies')
    // Only the mobile tab carries a background fill when active; the desktop
    // inline link uses an underline span, not bg-(--accent-soft).
    const active = links.find((el) => el.className.includes('bg-(--accent-soft)'))
    expect(active).toHaveClass('bg-(--accent-soft)')
  })
})
