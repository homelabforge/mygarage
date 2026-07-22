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

  it('highlights the /supplies link as active when on that route', () => {
    setup('/supplies')

    const links = screen.getAllByRole('link', { name: 'supplies' })
    // Mobile nav link uses the active-state classes; desktop nav has no active-state styling.
    const activeLink = links.find(el => el.className.includes('text-primary-500'))
    expect(activeLink).toHaveClass('text-primary-500')
  })
})
