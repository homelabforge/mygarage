import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { render } from '../../__tests__/test-utils'

// Bypass AuthProvider by mocking the hook directly.
vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({
    login: vi.fn().mockResolvedValue({ id: 1, username: 'test' }),
    user: null,
  }),
}))

// Mock axios so api module doesn't error out on import.
vi.mock('axios', () => {
  interface MockAxios {
    post: ReturnType<typeof vi.fn>
    get: ReturnType<typeof vi.fn>
    interceptors: {
      request: { use: ReturnType<typeof vi.fn>; eject: ReturnType<typeof vi.fn> }
      response: { use: ReturnType<typeof vi.fn>; eject: ReturnType<typeof vi.fn> }
    }
    create: ReturnType<typeof vi.fn>
  }
  const mockAxios: MockAxios = {
    post: vi.fn(() => Promise.resolve({ data: {} })),
    get: vi.fn(() => Promise.resolve({ data: {} })),
    interceptors: {
      request: { use: vi.fn(), eject: vi.fn() },
      response: { use: vi.fn(), eject: vi.fn() },
    },
    create: vi.fn(),
  }
  mockAxios.create = vi.fn(() => mockAxios)
  return { default: mockAxios }
})

import Login from '../Login'

let originalFetch: typeof globalThis.fetch

beforeEach(() => {
  originalFetch = globalThis.fetch
})

afterEach(() => {
  cleanup()
  globalThis.fetch = originalFetch
  vi.restoreAllMocks()
})

function mockOidcConfig(config: { enabled: boolean; provider_name?: string }): void {
  globalThis.fetch = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => config,
  }) as unknown as typeof globalThis.fetch
}

function mockOidcError(): void {
  globalThis.fetch = vi
    .fn()
    .mockRejectedValue(new Error('network')) as unknown as typeof globalThis.fetch
}

// i18next returns raw keys in tests (no full config). Query by placeholder +
// button-text literals that don't go through translation, or by role + literal
// i18n key strings.
const USERNAME_PLACEHOLDER = /username or email/i
const PASSWORD_PLACEHOLDER = /enter your password/i
const SSO_BUTTON = /login\.oidcSignIn/i // raw key — t() expands {{provider}} into the key template
const TOGGLE_BUTTON = /continueWithPassword/i // raw key

describe('Login Page — progressive disclosure', () => {
  it('with OIDC disabled: password fields render immediately; no SSO', async () => {
    mockOidcConfig({ enabled: false })
    render(<Login />)

    await waitFor(() => {
      expect(screen.getByPlaceholderText(USERNAME_PLACEHOLDER)).toBeInTheDocument()
    })
    expect(screen.getByPlaceholderText(PASSWORD_PLACEHOLDER)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: TOGGLE_BUTTON })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: SSO_BUTTON })).not.toBeInTheDocument()
  })

  it('with OIDC enabled: SSO + toggle visible; password fields hidden', async () => {
    mockOidcConfig({ enabled: true, provider_name: 'Authentik' })
    render(<Login />)

    // SSO button is present. i18next renders the raw key when translations
    // aren't wired — match on the raw key prefix.
    await waitFor(() => {
      expect(screen.getByRole('button', { name: SSO_BUTTON })).toBeInTheDocument()
    })
    expect(screen.getByRole('button', { name: TOGGLE_BUTTON })).toBeInTheDocument()
    expect(screen.queryByPlaceholderText(USERNAME_PLACEHOLDER)).not.toBeInTheDocument()
    expect(screen.queryByPlaceholderText(PASSWORD_PLACEHOLDER)).not.toBeInTheDocument()
  })

  it('clicking the toggle reveals the password form', async () => {
    const user = userEvent.setup()
    mockOidcConfig({ enabled: true, provider_name: 'Authentik' })
    render(<Login />)

    const toggle = await screen.findByRole('button', { name: TOGGLE_BUTTON })
    await user.click(toggle)

    expect(screen.getByPlaceholderText(USERNAME_PLACEHOLDER)).toBeInTheDocument()
    expect(screen.getByPlaceholderText(PASSWORD_PLACEHOLDER)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: TOGGLE_BUTTON })).not.toBeInTheDocument()
  })

  it('OIDC check network failure falls back to password-visible', async () => {
    mockOidcError()
    render(<Login />)

    await waitFor(() => {
      expect(screen.getByPlaceholderText(USERNAME_PLACEHOLDER)).toBeInTheDocument()
    })
    expect(screen.getByPlaceholderText(PASSWORD_PLACEHOLDER)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: SSO_BUTTON })).not.toBeInTheDocument()
  })
})
