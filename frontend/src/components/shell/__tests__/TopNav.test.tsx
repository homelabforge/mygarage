import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import * as ThemeContext from '../../../contexts/ThemeContext'
import * as AuthContext from '../../../contexts/AuthContext'
import TopNav from '../TopNav'

vi.mock('../../../contexts/ThemeContext')
vi.mock('../../../contexts/AuthContext')

function setup() {
  vi.spyOn(ThemeContext, 'useTheme').mockReturnValue({ theme: 'dark', toggleTheme: vi.fn(), setTheme: vi.fn() })
  vi.spyOn(AuthContext, 'useAuth').mockReturnValue({
    user: null, isAuthenticated: false, isAdmin: false, logout: vi.fn(), authMode: 'none',
  } as unknown as ReturnType<typeof AuthContext.useAuth>)
  render(
    <MemoryRouter>
      <TopNav />
    </MemoryRouter>
  )
}

describe('TopNav', () => {
  it('renders the inline nav behind the nav: breakpoint', () => {
    setup()
    const nav = screen.getByRole('navigation')
    expect(nav).toHaveClass('hidden', 'nav:flex')
  })

  it('renders the hamburger only in the tablet band', () => {
    setup()
    // jsdom applies no CSS, so this only pins the class string — it cannot verify
    // computed display. The real proof is the browser check (see task-10 fix report).
    expect(screen.getByRole('button', { name: 'openMenu' })).toHaveClass('max-md:hidden', 'nav:hidden')
  })

  it('toggling the hamburger mounts and unmounts the panel', () => {
    setup()
    // panel closed: the hamburger placeholder text is the only search trigger
    expect(screen.queryByRole('button', { name: 'searchPlaceholder' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'openMenu' }))
    expect(screen.getByRole('button', { name: 'searchPlaceholder' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'closeMenu' }))
    expect(screen.queryByRole('button', { name: 'searchPlaceholder' })).toBeNull()
  })
})
