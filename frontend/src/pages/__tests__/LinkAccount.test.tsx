import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { render } from '../../__tests__/test-utils'

const h = vi.hoisted(() => ({
  post: vi.fn(),
  get: vi.fn(),
  setCSRFToken: vi.fn(),
  refreshUser: vi.fn(),
}))

vi.mock('../../services/api', () => ({
  default: { post: h.post, get: h.get },
  setCSRFToken: h.setCSRFToken,
}))

// Bypass AuthProvider by mocking the hook directly, same pattern as Login.test.tsx.
vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({ refreshUser: h.refreshUser }),
}))

import LinkAccount from '../LinkAccount'

// What React Router keeps in history.state. The strip has to leave it alone.
const ROUTER_STATE = { usr: null, key: 'sso', idx: 0 }
const PASSWORD_LABEL = 'login.password'

// Where the callback's 302 lands: the token is in the fragment, never the query.
function arriveAt(url: string): void {
  window.history.replaceState(ROUTER_STATE, '', url)
}

async function linkWithPassword(): Promise<void> {
  const user = userEvent.setup()
  await user.type(screen.getByLabelText(PASSWORD_LABEL), 'testpassword123')
  await user.click(screen.getByRole('button', { name: 'oidc.linkAccount' }))
  await waitFor(() => expect(window.location.pathname).toBe('/'))
}

beforeEach(() => {
  h.post.mockResolvedValue({ data: { csrf_token: 'csrf-after-link' } })
  h.get.mockResolvedValue({ data: {} })
  h.refreshUser.mockResolvedValue(undefined)
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.clearAllMocks()
  window.history.replaceState(null, '', '/')
})

describe('LinkAccount: the pending link token rides in the fragment', () => {
  it('reads the token from the hash and strips it from the address bar', () => {
    arriveAt('/auth/link-account#token=pending-abc')
    const strip = vi.spyOn(window.history, 'replaceState')

    render(<LinkAccount />)

    expect(screen.getByLabelText(PASSWORD_LABEL)).toBeInTheDocument()
    expect(strip).toHaveBeenCalledWith(ROUTER_STATE, '', '/auth/link-account')
    expect(window.location.pathname).toBe('/auth/link-account')
    expect(window.location.hash).toBe('')
    expect(window.history.state).toEqual(ROUTER_STATE)
  })

  it('POSTs the token it read before the strip', async () => {
    arriveAt('/auth/link-account#token=pending-abc')
    render(<LinkAccount />)
    expect(window.location.hash).toBe('')

    await linkWithPassword()

    expect(h.post).toHaveBeenCalledWith('/auth/oidc/link-account', {
      token: 'pending-abc',
      password: 'testpassword123',
    })
  })

  it('keeps the token through StrictMode, which reads and strips twice', async () => {
    arriveAt('/auth/link-account#token=pending-abc')
    // StrictMode wraps the router, as in main.tsx. Nested under a provider that
    // mounts with it, React 19 never runs the effects twice.
    render(<LinkAccount />, { reactStrictMode: true })
    // The second effect pass finds no hash, and it mustn't bounce to login over it.
    expect(window.location.pathname).toBe('/auth/link-account')
    expect(window.location.hash).toBe('')

    await linkWithPassword()

    expect(h.post).toHaveBeenCalledWith('/auth/oidc/link-account', {
      token: 'pending-abc',
      password: 'testpassword123',
    })
  })

  // On purpose: the token shouldn't linger in the address bar, so a reload of the
  // stripped URL has nothing to read and the person starts SSO over. Don't "fix"
  // this by leaving the fragment in place.
  it('reload after the strip goes to login', async () => {
    arriveAt('/auth/link-account#token=pending-abc')
    const first = render(<LinkAccount />)
    expect(screen.getByLabelText(PASSWORD_LABEL)).toBeInTheDocument()
    expect(window.location.hash).toBe('')

    first.unmount()
    render(<LinkAccount />)

    await waitFor(() => expect(window.location.pathname).toBe('/login'))
    expect(screen.queryByLabelText(PASSWORD_LABEL)).not.toBeInTheDocument()
    expect(h.post).not.toHaveBeenCalled()
  })
})
