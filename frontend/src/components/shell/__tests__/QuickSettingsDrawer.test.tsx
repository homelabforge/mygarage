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
  put: vi.fn(),
  toastError: vi.fn(),
  state: { accent: 'blue', authed: true },
}))

vi.mock('../../../contexts/AccentContext', () => ({
  useAccent: () => ({ accent: h.state.accent, setAccent: h.setAccent }),
}))
vi.mock('../../../contexts/AuthContext', () => ({
  useAuth: () => ({ isAuthenticated: h.state.authed, refreshUser: h.refreshUser }),
}))
vi.mock('../../../services/api', () => ({ default: { put: h.put } }))
vi.mock('sonner', () => ({ toast: { error: h.toastError } }))

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
  h.put.mockResolvedValue({})
})

describe('QuickSettingsDrawer', () => {
  it('opens from the settings gear into a drawer', async () => {
    openDrawer()
    expect(await screen.findByRole('dialog', { name: 'quickSettings' })).toBeInTheDocument()
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
})
