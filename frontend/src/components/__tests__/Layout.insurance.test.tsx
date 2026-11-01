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
  // Counted by href, not accessible name: navItems.ts labels are `nav:` keys
  // and the global mock renders them raw. On phone, Insurance lives in the
  // More drawer (D1), which mounts nothing while closed, so only the inline
  // TopNav link is in the DOM. The hamburger panel is closed too (§7.2).
  it('renders the one inline nav link to /insurance', () => {
    setup()
    const links = screen.getAllByRole('link').filter((l) => l.getAttribute('href') === '/insurance')
    expect(links).toHaveLength(1)
  })

  it('marks the phone More tab active on /insurance', () => {
    setup('/insurance')
    expect(screen.getByRole('button', { name: 'more' })).toHaveClass('bg-(--accent-soft)')
  })
})
