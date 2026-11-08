import { describe, it, expect, vi, beforeEach } from 'vitest'
import { useState } from 'react'
import { render, screen, waitFor, act } from '@testing-library/react'
import { renderWithQueryClient } from '@/__tests__/queryClient'
import { AuthProvider, useAuth } from '../AuthContext'

// Mock the api module
vi.mock('../../services/api', () => {
  const mockApi = {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
    interceptors: {
      request: { use: vi.fn() },
      response: { use: vi.fn() },
    },
    defaults: { headers: { common: {} } },
  }
  return {
    default: mockApi,
    setCSRFToken: vi.fn(),
    getCSRFToken: vi.fn(),
    clearCSRFToken: vi.fn(),
    setApiAuthMode: vi.fn(),
  }
})

// Re-import after mock
import api, { setCSRFToken, clearCSRFToken, getCSRFToken } from '../../services/api'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const mockedApi = api as any

// Test component to expose auth context values
function AuthConsumer() {
  const { user, isAuthenticated, isAdmin, loading, authMode, login, logout, register } = useAuth()
  // Captures whatever login()/register() reject with, unmodified, so tests can
  // inspect its shape (real AxiosError vs a pre-flattened plain Error).
  const [caughtError, setCaughtError] = useState<unknown>(null)
  return (
    <div>
      <span data-testid="loading">{String(loading)}</span>
      <span data-testid="authenticated">{String(isAuthenticated)}</span>
      <span data-testid="admin">{String(isAdmin)}</span>
      <span data-testid="auth-mode">{authMode}</span>
      <span data-testid="username">{user?.username || 'none'}</span>
      <span data-testid="caught-error-detail">
        {JSON.stringify(
          (caughtError as { response?: { data?: { detail?: unknown } } } | null)?.response?.data
            ?.detail ?? null
        )}
      </span>
      <span data-testid="caught-error-is-axios">
        {String(Boolean((caughtError as { isAxiosError?: boolean } | null)?.isAxiosError))}
      </span>
      <button onClick={() => login('testuser', 'password123')}>Login</button>
      <button onClick={() => login('testuser', 'wrongpass').catch(setCaughtError)}>
        Login (bad credentials)
      </button>
      <button onClick={() => logout()}>Logout</button>
      <button onClick={() => register('newuser', 'new@test.com', 'pass123')}>Register</button>
      <button onClick={() => register('newuser', 'new@test.com', 'weak').catch(setCaughtError)}>
        Register (weak password)
      </button>
    </div>
  )
}

describe('AuthContext', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    sessionStorage.clear()
  })

  it('useAuth throws when used outside AuthProvider', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})

    expect(() => render(<AuthConsumer />)).toThrow(
      'useAuth must be used within an AuthProvider'
    )
  })

  it('starts in loading state', () => {
    // Use a never-resolving promise to stay in loading
    mockedApi.get.mockReturnValue(new Promise(() => {}))

    renderWithQueryClient(
      <AuthProvider>
        <AuthConsumer />
      </AuthProvider>
    )

    expect(screen.getByTestId('loading')).toHaveTextContent('true')
  })

  it('loads auth mode from public settings', async () => {
    mockedApi.get.mockImplementation((url: string) => {
      if (url === '/settings/public') {
        return Promise.resolve({
          data: {
            settings: [{ key: 'auth_mode', value: 'local' }],
          },
        })
      }
      if (url === '/auth/me') {
        return Promise.resolve({
          data: { id: 1, username: 'testuser', email: 'test@test.com', is_admin: true },
        })
      }
      return Promise.reject(new Error('Not found'))
    })

    renderWithQueryClient(
      <AuthProvider>
        <AuthConsumer />
      </AuthProvider>
    )

    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('false')
      expect(screen.getByTestId('auth-mode')).toHaveTextContent('local')
      expect(screen.getByTestId('authenticated')).toHaveTextContent('true')
      expect(screen.getByTestId('username')).toHaveTextContent('testuser')
    })
  })

  it('does not call /auth/me when auth mode is none', async () => {
    // Regression guard for bug #98. In auth_mode='none' there is no logged-in
    // user, so /auth/me has nothing to return — with no cookie it 401s, and
    // the global axios response interceptor hard-redirects to /login on any
    // 401. loadUser must therefore decide auth_mode from /settings/public
    // FIRST and never probe /auth/me when auth is disabled. The 401 mock below
    // makes the test fail loudly if /auth/me is reintroduced into this path.
    mockedApi.get.mockImplementation((url: string) => {
      if (url === '/settings/public') {
        return Promise.resolve({
          data: { settings: [{ key: 'auth_mode', value: 'none' }] },
        })
      }
      if (url === '/auth/me') {
        return Promise.reject({ response: { status: 401 } })
      }
      return Promise.reject(new Error('Not found'))
    })

    renderWithQueryClient(
      <AuthProvider>
        <AuthConsumer />
      </AuthProvider>
    )

    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('false')
      expect(screen.getByTestId('auth-mode')).toHaveTextContent('none')
      expect(screen.getByTestId('authenticated')).toHaveTextContent('false')
    })

    const requestedUrls = mockedApi.get.mock.calls.map((call: unknown[]) => call[0])
    expect(requestedUrls).toContain('/settings/public')
    expect(requestedUrls).not.toContain('/auth/me')
  })

  it('handles 401 when cookie is expired', async () => {
    mockedApi.get.mockImplementation((url: string) => {
      if (url === '/settings/public') {
        return Promise.resolve({
          data: { settings: [{ key: 'auth_mode', value: 'local' }] },
        })
      }
      if (url === '/auth/me') {
        return Promise.reject({ response: { status: 401 } })
      }
      return Promise.reject(new Error('Not found'))
    })

    renderWithQueryClient(
      <AuthProvider>
        <AuthConsumer />
      </AuthProvider>
    )

    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('false')
      expect(screen.getByTestId('authenticated')).toHaveTextContent('false')
    })
  })

  it('login stores CSRF token and loads user', async () => {
    // Initial load: auth disabled
    mockedApi.get.mockResolvedValueOnce({
      data: { settings: [{ key: 'auth_mode', value: 'local' }] },
    })
    // Initial /auth/me fails
    mockedApi.get.mockRejectedValueOnce({ response: { status: 401 } })

    renderWithQueryClient(
      <AuthProvider>
        <AuthConsumer />
      </AuthProvider>
    )

    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('false')
    })

    // Mock login response
    mockedApi.post.mockResolvedValueOnce({
      data: { access_token: 'jwt-token', csrf_token: 'csrf-abc' },
    })
    // Mock getCSRFToken to return the stored token
    vi.mocked(getCSRFToken).mockReturnValue('csrf-abc')
    // Mock /auth/me after login
    mockedApi.get.mockResolvedValueOnce({
      data: { id: 1, username: 'testuser', email: 'test@test.com', is_admin: false },
    })

    await act(async () => {
      screen.getByText('Login').click()
    })

    await waitFor(() => {
      expect(screen.getByTestId('authenticated')).toHaveTextContent('true')
      expect(screen.getByTestId('username')).toHaveTextContent('testuser')
    })

    expect(setCSRFToken).toHaveBeenCalledWith('csrf-abc')
  })

  it('logout clears user and CSRF token', async () => {
    // Initial load: authenticated
    mockedApi.get.mockImplementation((url: string) => {
      if (url === '/settings/public') {
        return Promise.resolve({
          data: { settings: [{ key: 'auth_mode', value: 'local' }] },
        })
      }
      if (url === '/auth/me') {
        return Promise.resolve({
          data: { id: 1, username: 'testuser', email: 'test@test.com', is_admin: true },
        })
      }
      return Promise.reject(new Error('Not found'))
    })

    renderWithQueryClient(
      <AuthProvider>
        <AuthConsumer />
      </AuthProvider>
    )

    await waitFor(() => {
      expect(screen.getByTestId('authenticated')).toHaveTextContent('true')
    })

    // Mock logout API call
    mockedApi.post.mockResolvedValueOnce({})

    await act(async () => {
      screen.getByText('Logout').click()
    })

    await waitFor(() => {
      expect(screen.getByTestId('authenticated')).toHaveTextContent('false')
      expect(screen.getByTestId('username')).toHaveTextContent('none')
    })

    expect(clearCSRFToken).toHaveBeenCalled()
  })

  it('register calls API with correct payload', async () => {
    // Initial load
    mockedApi.get.mockResolvedValueOnce({
      data: { settings: [{ key: 'auth_mode', value: 'none' }] },
    })

    renderWithQueryClient(
      <AuthProvider>
        <AuthConsumer />
      </AuthProvider>
    )

    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('false')
    })

    mockedApi.post.mockResolvedValueOnce({ data: {} })

    await act(async () => {
      screen.getByText('Register').click()
    })

    expect(mockedApi.post).toHaveBeenCalledWith('/auth/register', {
      username: 'newuser',
      email: 'new@test.com',
      password: 'pass123',
    })
  })

  // Regression fence for Task 10c review CRITICAL 1: register()/login() used to
  // catch the AxiosError, collapse it to `new Error(response.data.detail || ...)`,
  // and re-throw — a 422's `detail` is an ARRAY, so the array got string-coerced
  // into "[object Object],[object Object]" and the original AxiosError shape
  // (needed by parseApiError/applyServerErrors downstream in Login.tsx/
  // Register.tsx) was destroyed. Both must now propagate the original error
  // untouched.
  it('register propagates the original AxiosError (array detail intact) instead of collapsing it to a string Error', async () => {
    mockedApi.get.mockResolvedValueOnce({
      data: { settings: [{ key: 'auth_mode', value: 'none' }] },
    })

    renderWithQueryClient(
      <AuthProvider>
        <AuthConsumer />
      </AuthProvider>
    )

    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('false')
    })

    const problemDetail = [
      { type: 'value_error', loc: ['body', 'password'], msg: 'Password must contain at least one special character' },
    ]
    mockedApi.post.mockRejectedValueOnce({
      isAxiosError: true,
      message: 'Request failed with status code 422',
      response: { status: 422, data: { detail: problemDetail } },
    })

    await act(async () => {
      screen.getByText('Register (weak password)').click()
    })

    await waitFor(() => {
      expect(screen.getByTestId('caught-error-is-axios')).toHaveTextContent('true')
    })
    // The array survived intact — NOT stringified via `new Error(array)`
    // (which would render as "[object Object],[object Object]"), NOT dropped.
    const rendered = screen.getByTestId('caught-error-detail').textContent
    expect(rendered).not.toContain('[object Object]')
    expect(JSON.parse(rendered ?? 'null')).toEqual(problemDetail)
  })

  it('login propagates the original AxiosError instead of collapsing it to a string Error', async () => {
    mockedApi.get.mockResolvedValueOnce({
      data: { settings: [{ key: 'auth_mode', value: 'none' }] },
    })

    renderWithQueryClient(
      <AuthProvider>
        <AuthConsumer />
      </AuthProvider>
    )

    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('false')
    })

    mockedApi.post.mockRejectedValueOnce({
      isAxiosError: true,
      message: 'Request failed with status code 401',
      response: { status: 401, data: { detail: 'Incorrect username or password' } },
    })

    await act(async () => {
      screen.getByText('Login (bad credentials)').click()
    })

    await waitFor(() => {
      expect(screen.getByTestId('caught-error-is-axios')).toHaveTextContent('true')
    })
    expect(screen.getByTestId('caught-error-detail')).toHaveTextContent(
      'Incorrect username or password'
    )
  })

  it('isAdmin reflects user admin status', async () => {
    mockedApi.get.mockImplementation((url: string) => {
      if (url === '/settings/public') {
        return Promise.resolve({
          data: { settings: [{ key: 'auth_mode', value: 'local' }] },
        })
      }
      if (url === '/auth/me') {
        return Promise.resolve({
          data: { id: 1, username: 'admin', email: 'admin@test.com', is_admin: true },
        })
      }
      return Promise.reject(new Error('Not found'))
    })

    renderWithQueryClient(
      <AuthProvider>
        <AuthConsumer />
      </AuthProvider>
    )

    await waitFor(() => {
      expect(screen.getByTestId('admin')).toHaveTextContent('true')
    })
  })

  it('asks for public settings before /auth/me, and only once they answer', async () => {
    // Bug #98: probing /auth/me before the mode is known 401s into /login.
    let answerSettings: (value: unknown) => void = () => {}
    mockedApi.get.mockImplementation((url: string) => {
      if (url === '/settings/public') {
        return new Promise((resolve) => {
          answerSettings = resolve
        })
      }
      if (url === '/auth/me') {
        return Promise.resolve({ data: { id: 1, username: 'testuser', is_admin: false } })
      }
      return Promise.reject(new Error('Not found'))
    })

    renderWithQueryClient(
      <AuthProvider>
        <AuthConsumer />
      </AuthProvider>
    )

    await waitFor(() => expect(mockedApi.get).toHaveBeenCalledWith('/settings/public'))
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(mockedApi.get).not.toHaveBeenCalledWith('/auth/me')

    await act(async () => {
      answerSettings({ data: { settings: [{ key: 'auth_mode', value: 'local' }] } })
    })
    await waitFor(() => expect(screen.getByTestId('username')).toHaveTextContent('testuser'))
    const urls = mockedApi.get.mock.calls.map((call: unknown[]) => call[0])
    expect(urls.indexOf('/settings/public')).toBeLessThan(urls.indexOf('/auth/me'))
  })

  it('boots into the shared public settings query, not a private copy', async () => {
    const rows = [
      { key: 'auth_mode', value: 'none' },
      { key: 'nhtsa_enabled', value: 'false' },
    ]
    mockedApi.get.mockImplementation((url: string) =>
      url === '/settings/public'
        ? Promise.resolve({ data: { settings: rows } })
        : Promise.reject(new Error('Not found')),
    )

    const { client } = renderWithQueryClient(
      <AuthProvider>
        <AuthConsumer />
      </AuthProvider>
    )

    await waitFor(() => expect(screen.getByTestId('loading')).toHaveTextContent('false'))
    expect(client.getQueryData(['settings', 'public'])).toEqual(rows)
  })
})
