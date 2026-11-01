import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import { cleanup, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { render } from '../../__tests__/test-utils'
import commonEn from '../../locales/en/common.json'
import { registeredFieldNames, validationError, whereA422Lands } from '../../__tests__/serverErrors'

// The SSO sentences resolve against the real English bundle, so these tests read
// what a person sees and a typo in common.json fails here. Every other key stays
// raw, which is what the older tests below match on. A miss returns the key, as
// i18next does, and that's the leak the unknown-code test watches for.
vi.mock('react-i18next', () => {
  const t = (key: string): string => {
    if (!key.startsWith('login.ssoError.')) return key
    const found = key.split('.').reduce<unknown>(
      (node, part) => (node && typeof node === 'object' ? (node as Record<string, unknown>)[part] : undefined),
      commonEn,
    )
    return typeof found === 'string' ? found : key
  }
  const i18n = { language: 'en', changeLanguage: (): Promise<void> => Promise.resolve() }
  return {
    useTranslation: () => ({ t, i18n }),
    Trans: ({ children }: { children: ReactNode }) => children,
    initReactI18next: { type: '3rdParty', init: () => {} },
  }
})

// Bypass AuthProvider by mocking the hook directly. Hoisted so a test can
// make the sign-in fail.
const loginMock = vi.hoisted(() => vi.fn())
vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({
    login: loginMock,
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
  loginMock.mockReset().mockResolvedValue({ id: 1, username: 'test' })
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

// i18next returns raw keys in tests (no full config), so every query below
// matches the i18n key rather than the English copy.
const USERNAME_PLACEHOLDER = /^loginPage\.usernamePlaceholder$/
const PASSWORD_PLACEHOLDER = /^loginPage\.passwordPlaceholder$/
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

// What each sso_error code should put on the page. The five refusals and
// no_account are the backend's own English messages (SSO_ACCOUNT_DISABLED in
// app/constants/oidc.py, the rest in app/services/oidc/users.py), word for word.
const SSO_SENTENCES: Record<string, string> = {
  account_disabled: 'User account is disabled',
  email_linked_elsewhere:
    'This email belongs to an account that is linked to a different sign-in. Ask an administrator to allow an SSO relink for it.',
  email_no_password:
    'An account with this email exists but has no password to confirm it. Ask an administrator to allow an SSO relink for it.',
  username_linked_elsewhere:
    'This username belongs to an account that is linked to a different sign-in. Ask an administrator to allow an SSO relink for it.',
  username_no_password:
    'An account with this username exists but has no password to confirm it. Ask an administrator to allow an SSO relink for it.',
  no_account:
    'No MyGarage account matches this sign-in, and automatic account creation is off. Ask an administrator to create your account.',
  cancelled: 'Sign-in was cancelled.',
  expired: 'This sign-in took too long or was already used. Please try again.',
  failed: "Single sign-on didn't work. Please try again, or ask an administrator to check the SSO settings.",
  rate_limited: 'Too many sign-in attempts. Wait a minute, then try again.',
}

describe('Login Page: SSO error from the redirect', () => {
  // The helper wraps BrowserRouter, which reads the real window URL.
  function visit(search: string): void {
    window.history.replaceState(null, '', `/login${search}`)
  }

  afterEach(() => {
    window.history.replaceState(null, '', '/')
  })

  it.each(Object.entries(SSO_SENTENCES))('?sso_error=%s shows its sentence', async (code, sentence) => {
    mockOidcConfig({ enabled: true, provider_name: 'Rauthy' })
    visit(`?sso_error=${code}`)
    render(<Login />)

    expect(await screen.findByText(sentence)).toBeInTheDocument()
  })

  it('the banner is an alert, so a screen reader reads it out', async () => {
    mockOidcConfig({ enabled: true, provider_name: 'Rauthy' })
    visit('?sso_error=failed')
    render(<Login />)

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(SSO_SENTENCES.failed)
  })

  it('an unknown code shows the generic sentence, never its own text', async () => {
    mockOidcConfig({ enabled: true, provider_name: 'Rauthy' })
    visit('?sso_error=Call%20555')
    render(<Login />)

    await screen.findByRole('button', { name: SSO_BUTTON })
    expect(document.body.textContent).not.toContain('Call 555')
    expect(screen.getByText(SSO_SENTENCES.failed)).toBeInTheDocument()
  })

  it('no sso_error shows no SSO sentence', async () => {
    mockOidcConfig({ enabled: true, provider_name: 'Rauthy' })
    visit('')
    render(<Login />)

    await screen.findByRole('button', { name: SSO_BUTTON })
    for (const sentence of Object.values(SSO_SENTENCES)) {
      expect(screen.queryByText(sentence)).not.toBeInTheDocument()
    }
    expect(document.body.textContent).not.toContain('login.ssoError')
  })

  it('drops sso_error from the URL after mount and keeps the sentence', async () => {
    mockOidcConfig({ enabled: true, provider_name: 'Rauthy' })
    visit('?sso_error=expired')
    render(<Login />)

    expect(await screen.findByText(SSO_SENTENCES.expired)).toBeInTheDocument()
    await waitFor(() => {
      expect(window.location.search).toBe('')
    })
    expect(window.location.pathname).toBe('/login')
    expect(screen.getByText(SSO_SENTENCES.expired)).toBeInTheDocument()
  })
})

describe('Login Page: a rejected sign-in', () => {
  const signIn = async (): Promise<void> => {
    const user = userEvent.setup()
    await user.type(await screen.findByPlaceholderText(USERNAME_PLACEHOLDER), 'jamey')
    await user.type(screen.getByPlaceholderText(PASSWORD_PLACEHOLDER), 'hunter22')
    await user.click(screen.getByRole('button', { name: 'login.submit' }))
  }
  // The field messages are alerts too, so the banner is the alert that isn't one of them.
  const banner = (): HTMLElement | null =>
    screen.queryAllByRole('alert').find((el) => el.tagName !== 'P') ?? null

  it('a non-422 failure shows the banner and no field error', async () => {
    mockOidcConfig({ enabled: false })
    loginMock.mockRejectedValueOnce(new Error('Network Error'))
    render(<Login />)
    await signIn()

    await waitFor(() => expect(banner()).toHaveTextContent('Failed to login.signInAction. Network Error'))
    expect(screen.getAllByRole('alert')).toHaveLength(1)
  })

  it('a 422 on username shows under username and no banner', async () => {
    mockOidcConfig({ enabled: false })
    loginMock.mockRejectedValueOnce(validationError({ username: 'String should have at most 100 characters' }))
    render(<Login />)
    await signIn()

    const username = screen.getByPlaceholderText(USERNAME_PLACEHOLDER)
    await waitFor(() =>
      expect(username.parentElement).toHaveTextContent('String should have at most 100 characters')
    )
    expect(banner()).toBeNull()
  })

  // Named controls that aren't payload fields go here. None today.
  const UI_ONLY: string[] = []

  // Guard for knownFields drift and silent fields: a 422 on any field the form
  // registers has to show up under that field. Mutants: drop a name from
  // knownFields (it goes to the banner), or drop a field's error (it goes silent).
  it('guard: a 422 on each field shows under it', async () => {
    mockOidcConfig({ enabled: false })
    render(<Login />)
    await signIn()
    await waitFor(() => expect(loginMock).toHaveBeenCalledTimes(1))
    const form = screen.getByPlaceholderText(USERNAME_PLACEHOLDER).closest('form') as HTMLFormElement
    const names = registeredFieldNames(form, UI_ONLY)
    // An empty sweep would pass, so pin the names it must contain.
    expect(names).toEqual(expect.arrayContaining(['username', 'password']))

    const wrong: string[] = []
    for (const name of names) {
      const got = await whereA422Lands(form, loginMock, name, `bad ${name}`, banner)
      if (got !== 'field') wrong.push(`${name}: ${got}`)
    }
    expect(wrong).toEqual([])
  })
})
