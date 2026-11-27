import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import * as AuthContext from '../../../contexts/AuthContext'
import RightCluster from '../RightCluster'

// RightCluster toggles theme via useThemePreference (local apply + account PUT);
// mock the hook so the toggle handler is observable without a live provider.
const themeMocks = vi.hoisted(() => ({ toggleTheme: vi.fn(), setTheme: vi.fn() }))
vi.mock('../../../hooks/useThemePreference', () => ({
  useThemePreference: () => ({ theme: 'dark', toggleTheme: themeMocks.toggleTheme, setTheme: themeMocks.setTheme }),
}))
vi.mock('../../../contexts/AuthContext')
// Stub only useNavigate, so where logout sends you is observable.
const nav = vi.hoisted(() => ({ navigate: vi.fn(), toastError: vi.fn() }))
vi.mock('react-router-dom', async (importOriginal) => ({
  ...(await importOriginal<typeof import('react-router-dom')>()),
  useNavigate: () => nav.navigate,
}))
vi.mock('sonner', () => ({ toast: { error: nav.toastError } }))
// QuickSettingsDrawer (a child) reads useAccent; stub it — not under test here.
vi.mock('../../../contexts/AccentContext', () => ({
  useAccent: () => ({ accent: 'blue', setAccent: vi.fn() }),
}))

beforeEach(() => {
  vi.clearAllMocks()
})

function setup(overrides: Partial<ReturnType<typeof AuthContext.useAuth>> = {}) {
  vi.spyOn(AuthContext, 'useAuth').mockReturnValue({
    user: { id: 1, username: 'jamey', email: 'j@x', is_admin: false },
    isAuthenticated: true,
    isAdmin: false,
    logout: vi.fn(),
    authMode: 'local',
    ...overrides,
  } as unknown as ReturnType<typeof AuthContext.useAuth>)
  // The quick-settings drawer hosts the units card, which reads the query
  // client; App.tsx provides one around the whole shell.
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <RightCluster />
      </MemoryRouter>
    </QueryClientProvider>
  )
}

describe('RightCluster', () => {
  it('theme toggle calls toggleTheme', () => {
    setup()
    fireEvent.click(screen.getByRole('button', { name: 'themeToggle' }))
    expect(themeMocks.toggleTheme).toHaveBeenCalledOnce()
  })

  it('the settings gear is a button that opens the quick-settings drawer, not a nav link', async () => {
    setup()
    // nav.settings (selectors.ts:14) is defined-but-never-called; the gear is a button.
    expect(screen.queryByRole('link', { name: 'settings' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'quickSettings' }))
    expect(await screen.findByRole('dialog', { name: 'quickSettings' })).toBeInTheDocument()
  })

  // At 1280 in English the badge was the 61px that pushed the top links into
  // the hamburger for every admin, so it only shows in the 768-899 band now.
  it('shows the admin badge only in the tablet band, never next to the inline links', () => {
    setup({ isAdmin: true })
    const badge = screen.getByText('admin').closest('span[aria-hidden]')
    expect(badge).toHaveClass('max-md:hidden', 'nav:hidden')
  })

  it('renders an avatar from the username', () => {
    setup()
    expect(screen.getByRole('img', { name: 'jamey' })).toBeInTheDocument()
  })

  it('hides the search box below the nav breakpoint via the band class', () => {
    setup()
    // NavSearch's button hardcodes `inline-flex`, which beats a plain `hidden` in
    // the source-order cascade tie — so the band gate is a media-scoped `max-nav:hidden`
    // (hide <900, visible >=900 via the base inline-flex), NOT `hidden nav:flex`.
    // This class-string assertion cannot prove the box actually hides (jsdom has no
    // CSS); the real proof is the Task 16 browser computed-display sweep.
    expect(screen.getByRole('button', { name: 'search' })).toHaveClass('max-nav:hidden')
  })

  it('shows a login link and no avatar when signed out (auth enabled)', () => {
    // C1: authMode:'none' hides the whole auth cluster, so there is NO login
    // link to find. Drive auth enabled but signed out instead.
    setup({ authMode: 'local', isAuthenticated: false, user: null })
    expect(screen.queryByRole('img', { name: 'jamey' })).toBeNull()
    expect(screen.getByRole('link', { name: /login/ })).toHaveAttribute('href', '/login')
  })

  it('logs out and goes to /login once the server says so', async () => {
    const logout = vi.fn().mockResolvedValue(true)
    setup({ logout })
    fireEvent.click(screen.getByRole('button', { name: 'logout' }))
    await waitFor(() => expect(nav.navigate.mock.calls).toStrictEqual([['/login']]))
    expect(logout).toHaveBeenCalledOnce()
    expect(nav.toastError).not.toHaveBeenCalled()
  })

  it("stays put and says so when the logout didn't reach the server", async () => {
    const logout = vi.fn().mockResolvedValue(false)
    setup({ logout })
    fireEvent.click(screen.getByRole('button', { name: 'logout' }))

    // Pins out navigating before (or regardless of) the answer: the login page
    // would look signed out while the session cookie is still live.
    await waitFor(() => expect(nav.toastError).toHaveBeenCalledWith('logoutFailed'))
    expect(nav.navigate).not.toHaveBeenCalled()
  })

  it('hides the whole auth cluster (no avatar, no login) when auth is disabled', () => {
    setup({ authMode: 'none', isAuthenticated: false, user: null })
    expect(screen.queryByRole('img', { name: 'jamey' })).toBeNull()
    expect(screen.queryByRole('link', { name: /login/ })).toBeNull()
  })
})
