import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import * as AuthContext from '../../contexts/AuthContext'
import * as ThemeContext from '../../contexts/ThemeContext'
import Layout from '../Layout'

vi.mock('../../contexts/AuthContext')
vi.mock('../../contexts/ThemeContext')

function setup(initialPath = '/supplies') {
  vi.spyOn(AuthContext, 'useAuth').mockReturnValue({
    user: null,
    isAuthenticated: false,
    isAdmin: false,
    logout: vi.fn(),
    authMode: 'none',
  } as unknown as ReturnType<typeof AuthContext.useAuth>)
  vi.spyOn(ThemeContext, 'useTheme').mockReturnValue({
    theme: 'dark',
    toggleTheme: vi.fn(),
    setTheme: vi.fn(),
  })

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
  // Counted by href, not accessible name: both navs now source labels from
  // navItems.ts as `nav:supplies` (namespace-qualified for the i18n gate, G5),
  // so the mock renders the raw key as the name. The href is stable and both
  // links point at /supplies. The hamburger panel is closed by default, so the
  // count stays 2 (inline TopNav link + MobileTabBar tab), not 3 — §7.2.
  it('renders both nav links to /supplies', () => {
    setup()
    const links = screen.getAllByRole('link').filter((l) => l.getAttribute('href') === '/supplies')
    expect(links).toHaveLength(2)
  })

  it('marks the mobile /supplies tab active on that route', () => {
    setup('/supplies')
    const links = screen.getAllByRole('link').filter((l) => l.getAttribute('href') === '/supplies')
    // Retokenized active class (MobileTabBar): the mobile tab carries
    // bg-(--accent-soft); the inline desktop link uses an underline span, not a
    // fill. This replaces the old literal text-primary-500 assertion (§7.2).
    const active = links.find((el) => el.className.includes('bg-(--accent-soft)'))
    expect(active).toHaveClass('bg-(--accent-soft)')
  })
})
