import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import * as ThemeContext from '../../../contexts/ThemeContext'
import * as AuthContext from '../../../contexts/AuthContext'
import RightCluster from '../RightCluster'

vi.mock('../../../contexts/ThemeContext')
vi.mock('../../../contexts/AuthContext')

function setup(overrides: Partial<ReturnType<typeof AuthContext.useAuth>> = {}) {
  const toggleTheme = vi.fn()
  vi.spyOn(ThemeContext, 'useTheme').mockReturnValue({ theme: 'dark', toggleTheme, setTheme: vi.fn() })
  vi.spyOn(AuthContext, 'useAuth').mockReturnValue({
    user: { id: 1, username: 'jamey', email: 'j@x', is_admin: false },
    isAuthenticated: true,
    isAdmin: false,
    logout: vi.fn(),
    authMode: 'local',
    ...overrides,
  } as unknown as ReturnType<typeof AuthContext.useAuth>)
  render(
    <MemoryRouter>
      <RightCluster />
    </MemoryRouter>
  )
  return { toggleTheme }
}

describe('RightCluster', () => {
  it('theme toggle calls toggleTheme', () => {
    const { toggleTheme } = setup()
    fireEvent.click(screen.getByRole('button', { name: 'themeToggle' }))
    expect(toggleTheme).toHaveBeenCalledOnce()
  })

  it('the settings gear is a button that opens the quick-settings drawer, not a nav link', async () => {
    setup()
    // nav.settings (selectors.ts:14) is defined-but-never-called; the gear is a button.
    expect(screen.queryByRole('link', { name: 'settings' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'quickSettings' }))
    expect(await screen.findByRole('dialog', { name: 'quickSettings' })).toBeInTheDocument()
  })

  it('renders an avatar from the username', () => {
    setup()
    expect(screen.getByRole('img', { name: 'jamey' })).toBeInTheDocument()
  })

  it('hides the search box below the nav breakpoint via the band class', () => {
    setup()
    expect(screen.getByRole('button', { name: 'search' })).toHaveClass('hidden', 'nav:flex')
  })

  it('shows a login link and no avatar when signed out (auth enabled)', () => {
    // C1: authMode:'none' hides the whole auth cluster, so there is NO login
    // link to find. Drive auth enabled but signed out instead.
    setup({ authMode: 'local', isAuthenticated: false, user: null })
    expect(screen.queryByRole('img', { name: 'jamey' })).toBeNull()
    expect(screen.getByRole('link', { name: /login/ })).toHaveAttribute('href', '/login')
  })

  it('hides the whole auth cluster (no avatar, no login) when auth is disabled', () => {
    setup({ authMode: 'none', isAuthenticated: false, user: null })
    expect(screen.queryByRole('img', { name: 'jamey' })).toBeNull()
    expect(screen.queryByRole('link', { name: /login/ })).toBeNull()
  })
})
