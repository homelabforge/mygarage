import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import * as AuthContext from '../../contexts/AuthContext'
import * as ThemeContext from '../../contexts/ThemeContext'
import Layout from '../Layout'

vi.mock('../../contexts/AuthContext')
vi.mock('../../contexts/ThemeContext')
// QuickSettingsDrawer (a descendant via TopNav→RightCluster) reads useAccent; stub it.
vi.mock('../../contexts/AccentContext', () => ({
  useAccent: () => ({ accent: 'blue', setAccent: vi.fn() }),
}))

function setup(initialPath = '/insurance') {
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
          <Route path="insurance" element={<div>Insurance Page</div>} />
        </Route>
      </Routes>
    </MemoryRouter>
  )
}

describe('Layout insurance nav', () => {
  // Counted by href, not accessible name: both navs now source labels from
  // navItems.ts as `nav:insurance` (namespace-qualified for the i18n gate, G5),
  // so the mock renders the raw key as the name. The href is stable and both
  // links point at /insurance. The hamburger panel is closed by default, so the
  // count stays 2 (inline TopNav link + MobileTabBar tab), not 3 — §7.2.
  it('renders both nav links to /insurance', () => {
    setup()
    const links = screen.getAllByRole('link').filter((l) => l.getAttribute('href') === '/insurance')
    expect(links).toHaveLength(2)
  })

  it('marks the mobile /insurance tab active on that route', () => {
    setup('/insurance')
    const links = screen.getAllByRole('link').filter((l) => l.getAttribute('href') === '/insurance')
    // Retokenized active class (MobileTabBar): the mobile tab carries
    // bg-(--accent-soft); the inline desktop link uses an underline span, not a
    // fill. This replaces the old literal text-primary-500 assertion (§7.2).
    const active = links.find((el) => el.className.includes('bg-(--accent-soft)'))
    expect(active).toHaveClass('bg-(--accent-soft)')
  })
})
