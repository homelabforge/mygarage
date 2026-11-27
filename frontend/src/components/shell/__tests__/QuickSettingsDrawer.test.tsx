import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { ACCENT_KEYS } from '../../../constants/accents'

// Hoisted so the vi.mock factories (which run before module init) can reach
// these. AccentContext + AuthContext throw outside their providers, so we mock
// them; api + sonner are mocked so we can assert the persistence boundary.
const h = vi.hoisted(() => ({
  setAccent: vi.fn(),
  refreshUser: vi.fn(),
    refreshPublicSettings: vi.fn(),
    householdTimeZone: null,
  logout: vi.fn(),
  navigate: vi.fn(),
  put: vi.fn(),
  toastError: vi.fn(),
  state: { accent: 'blue', authed: true, authMode: 'local' },
}))

vi.mock('../../../contexts/AccentContext', () => ({
  useAccent: () => ({ accent: h.state.accent, setAccent: h.setAccent }),
}))
vi.mock('../../../contexts/AuthContext', () => ({
  useAuth: () => ({
    isAuthenticated: h.state.authed,
    refreshUser: h.refreshUser,
    logout: h.logout,
    authMode: h.state.authMode,
  }),
}))
// Keep MemoryRouter + Link real; stub only useNavigate so logout routing is observable.
vi.mock('react-router-dom', async (importOriginal) => ({
  ...(await importOriginal<typeof import('react-router-dom')>()),
  useNavigate: () => h.navigate,
}))
vi.mock('../../../services/api', () => ({ default: { put: h.put } }))
vi.mock('sonner', () => ({ toast: { error: h.toastError } }))
// The preference controls have their own tests (settings/__tests__); here they
// are stand-ins, so this file checks only that the drawer hosts them.
vi.mock('../../settings/UnitPreferencesCard', () => ({ default: () => <div data-testid="pref-units" /> }))
vi.mock('../../settings/TimeFormatControl', () => ({ default: () => <div data-testid="pref-time" /> }))
vi.mock('../../settings/LanguageControl', () => ({ default: () => <div data-testid="pref-language" /> }))
vi.mock('../../settings/CurrencyControl', () => ({ default: () => <div data-testid="pref-currency" /> }))

import QuickSettingsDrawer from '../QuickSettingsDrawer'

function openDrawer() {
  render(
    <MemoryRouter>
      <QuickSettingsDrawer />
    </MemoryRouter>
  )
  fireEvent.click(screen.getByRole('button', { name: 'quickSettings' }))
}

beforeEach(() => {
  vi.clearAllMocks()
  h.state.accent = 'blue'
  h.state.authed = true
  h.state.authMode = 'local'
  h.put.mockResolvedValue({})
})

describe('QuickSettingsDrawer', () => {
  it('opens from the settings gear into a drawer', async () => {
    openDrawer()
    expect(await screen.findByRole('dialog', { name: 'quickSettings' })).toBeInTheDocument()
  })

  it("holds this person's display preferences, above About and All settings", async () => {
    openDrawer()
    // Loaded lazily, on the drawer's first open.
    await screen.findByTestId('pref-units')

    const order = ['pref-units', 'pref-time', 'pref-language', 'pref-currency'].map((id) =>
      screen.getByTestId(id),
    )
    order.push(screen.getByRole('link', { name: /about/ }))
    for (let i = 1; i < order.length; i++) {
      expect(order[i - 1].compareDocumentPosition(order[i]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    }
  })

  it('links to About and to full Settings', async () => {
    openDrawer()
    expect(await screen.findByRole('link', { name: /allSettings/ })).toHaveAttribute(
      'href',
      '/settings'
    )
    expect(screen.getByRole('link', { name: /about/ })).toHaveAttribute('href', '/about')
  })

  it('renders one swatch per accent, with the current accent pressed', async () => {
    h.state.accent = 'blue'
    openDrawer()
    await screen.findByRole('dialog', { name: 'quickSettings' })
    for (const key of ACCENT_KEYS) {
      expect(screen.getByRole('button', { name: `accents.${key}` })).toBeInTheDocument()
    }
    expect(screen.getByRole('button', { name: 'accents.blue' })).toHaveAttribute(
      'aria-pressed',
      'true'
    )
    expect(screen.getByRole('button', { name: 'accents.violet' })).toHaveAttribute(
      'aria-pressed',
      'false'
    )
  })

  it('applies the picked accent locally with the exact key', async () => {
    openDrawer()
    fireEvent.click(await screen.findByRole('button', { name: 'accents.violet' }))
    expect(h.setAccent.mock.calls).toStrictEqual([['violet']])
  })

  it('persists to the account (exact payload) and refreshes when authenticated', async () => {
    h.state.authed = true
    openDrawer()
    fireEvent.click(await screen.findByRole('button', { name: 'accents.red' }))
    await waitFor(() => expect(h.put).toHaveBeenCalled())
    expect(h.put.mock.calls).toStrictEqual([['/auth/me', { accent_color: 'red' }]])
    await waitFor(() => expect(h.refreshUser).toHaveBeenCalledTimes(1))
  })

  it('does NOT persist when unauthenticated (localStorage-only path)', async () => {
    h.state.authed = false
    openDrawer()
    fireEvent.click(await screen.findByRole('button', { name: 'accents.teal' }))
    expect(h.setAccent.mock.calls).toStrictEqual([['teal']])
    expect(h.put).not.toHaveBeenCalled()
    expect(h.refreshUser).not.toHaveBeenCalled()
  })

  it('surfaces an error toast when the save fails, keeping the local apply', async () => {
    h.state.authed = true
    h.put.mockRejectedValue(new Error('boom'))
    openDrawer()
    fireEvent.click(await screen.findByRole('button', { name: 'accents.green' }))
    await waitFor(() => expect(h.toastError).toHaveBeenCalledWith('accentError'))
    expect(h.setAccent.mock.calls).toStrictEqual([['green']])
  })

  it('shows a logout row that logs out and routes to /login when authed', async () => {
    h.logout.mockResolvedValue(true)
    openDrawer()
    fireEvent.click(await screen.findByRole('button', { name: 'logout' }))
    expect(h.logout).toHaveBeenCalledOnce()
    await waitFor(() => expect(h.navigate.mock.calls).toStrictEqual([['/login']]))
    expect(h.toastError).not.toHaveBeenCalled()
  })

  it("keeps the drawer open and says so when the logout didn't reach the server", async () => {
    h.logout.mockResolvedValue(false)
    openDrawer()
    fireEvent.click(await screen.findByRole('button', { name: 'logout' }))

    // Pins out navigating regardless of the answer: you'd land on /login still signed in.
    await waitFor(() => expect(h.toastError).toHaveBeenCalledWith('logoutFailed'))
    expect(h.navigate).not.toHaveBeenCalled()
    expect(screen.getByRole('dialog', { name: 'quickSettings' })).toBeInTheDocument()
  })

  it('hides the logout row when auth is disabled (authMode none)', async () => {
    h.state.authMode = 'none'
    openDrawer()
    await screen.findByRole('dialog', { name: 'quickSettings' })
    expect(screen.queryByRole('button', { name: 'logout' })).toBeNull()
  })

  it('hides the logout row when signed out', async () => {
    h.state.authed = false
    openDrawer()
    await screen.findByRole('dialog', { name: 'quickSettings' })
    expect(screen.queryByRole('button', { name: 'logout' })).toBeNull()
  })
})
