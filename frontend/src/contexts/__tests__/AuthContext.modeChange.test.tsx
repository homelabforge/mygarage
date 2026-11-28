/**
 * Turning sign-in off has to drop the signed-in user, or Share, the account
 * menu and isAdmin stay on screen until a reload, and the server 400s them.
 * Another tab catches up on its next visibility refresh.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { screen, waitFor, act } from '@testing-library/react'
import { renderWithQueryClient } from '@/__tests__/queryClient'
import { AuthProvider, useAuth } from '../AuthContext'

vi.mock('../../services/api', () => ({
  default: { get: vi.fn(), post: vi.fn() },
  setCSRFToken: vi.fn(),
  getCSRFToken: vi.fn(),
  clearCSRFToken: vi.fn(),
  setApiAuthMode: vi.fn(),
  setAuthStaleHandler: vi.fn(),
}))

import api, { setApiAuthMode, setAuthStaleHandler } from '../../services/api'

const mockedApi = vi.mocked(api)
const ADMIN = { id: 1, username: 'alice', is_admin: true }

function serve(mode: string): void {
  mockedApi.get.mockImplementation((url: string) => {
    if (url === '/settings/public') {
      return Promise.resolve({ data: { settings: [{ key: 'auth_mode', value: mode }] } })
    }
    if (url === '/auth/me') return Promise.resolve({ data: ADMIN })
    return Promise.resolve({ data: {} })
  })
}

// The handler AuthProvider handed the api module last.
function staleHandler(): () => void {
  const calls = vi.mocked(setAuthStaleHandler).mock.calls
  const handler = calls[calls.length - 1]?.[0]
  if (!handler) throw new Error('AuthProvider has no stale-auth handler registered')
  return handler
}

const settingsReads = (): number =>
  mockedApi.get.mock.calls.filter(([u]) => u === '/settings/public').length

function Probe() {
  const { isAuthenticated, isAdmin, authMode, refreshUser, loading, publicSettingsLoaded } = useAuth()
  return (
    <div>
      <span data-testid="state">{`${authMode}:${isAuthenticated}:${isAdmin}`}</span>
      <span data-testid="loaded">{String(publicSettingsLoaded)}</span>
      <button disabled={loading} onClick={() => void refreshUser()}>refresh</button>
    </div>
  )
}

let nowSpy: ReturnType<typeof vi.spyOn>

beforeEach(() => {
  vi.clearAllMocks()
  nowSpy = vi.spyOn(Date, 'now').mockReturnValue(1_000_000)
})

afterEach(() => {
  nowSpy.mockRestore()
})

describe('AuthContext follows the sign-in mode', () => {
  it('a refresh that finds sign-in off drops the signed-in user', async () => {
    serve('local')
    renderWithQueryClient(<AuthProvider><Probe /></AuthProvider>)
    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('local:true:true'))

    serve('none')
    screen.getByRole('button').click()

    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('none:false:false'))
  })

  it('a refresh that finds sign-in on tells the api before it asks for the user', async () => {
    serve('none')
    renderWithQueryClient(<AuthProvider><Probe /></AuthProvider>)
    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('none:false:false'))

    serve('local')
    screen.getByRole('button').click()

    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('local:true:true'))
    // In none mode a 401 doesn't send anyone to /login, so /auth/me has to go out in the new mode.
    const setMode = vi.mocked(setApiAuthMode).mock
    const localAt = setMode.calls.findIndex(([mode]) => mode === 'local')
    const meAt = mockedApi.get.mock.calls.findIndex(([url]) => url === '/auth/me')
    expect(localAt).toBeGreaterThanOrEqual(0)
    expect(meAt).toBeGreaterThanOrEqual(0)
    expect(setMode.invocationCallOrder[localAt]).toBeLessThan(mockedApi.get.mock.invocationCallOrder[meAt])
  })

  it('a visibility refresh that finds another mode reloads the user', async () => {
    serve('local')
    renderWithQueryClient(<AuthProvider><Probe /></AuthProvider>)
    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('local:true:true'))

    serve('none')
    nowSpy.mockReturnValue(1_000_000 + 61_000)
    act(() => {
      Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true })
      document.dispatchEvent(new Event('visibilitychange'))
    })

    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('none:false:false'))
  })

  it('a boot read that fails after a refresh landed still loads the user from that refresh', async () => {
    // Boot's read stays out until we fail it; the refresh's read answers right away.
    let failBoot: (err: Error) => void = () => {}
    let settingsCalls = 0
    mockedApi.get.mockImplementation((url: string) => {
      if (url === '/settings/public') {
        settingsCalls += 1
        if (settingsCalls === 1) {
          return new Promise((_resolve, reject) => {
            failBoot = reject
          })
        }
        return Promise.resolve({ data: { settings: [{ key: 'auth_mode', value: 'local' }] } })
      }
      if (url === '/auth/me') return Promise.resolve({ data: ADMIN })
      return Promise.resolve({ data: {} })
    })
    renderWithQueryClient(<AuthProvider><Probe /></AuthProvider>)
    await waitFor(() => expect(settingsCalls).toBe(1))

    act(() => {
      Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true })
      document.dispatchEvent(new Event('visibilitychange'))
    })
    await waitFor(() => expect(settingsCalls).toBe(2))
    // Let the refresh land while boot is still out.
    // Boot's read is still out, so only the refresh can have flipped this.
    await waitFor(() => expect(screen.getByTestId('loaded')).toHaveTextContent('true'))
    expect(mockedApi.get.mock.calls.some(([u]) => u === '/auth/me')).toBe(false)

    await act(async () => {
      failBoot(new Error('network down'))
    })

    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('local:true:true'))
    expect(screen.getByRole('button')).not.toBeDisabled()
  })

  it('a write refused with requires_sign_in drops the signed-in user', async () => {
    serve('local')
    renderWithQueryClient(<AuthProvider><Probe /></AuthProvider>)
    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('local:true:true'))

    // Same clock as boot's read, so the visibility throttle would still say no.
    serve('none')
    act(() => staleHandler()())

    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('none:false:false'))
    expect(setApiAuthMode).toHaveBeenLastCalledWith('none')
  })

  it('refused writes reread the public settings at most once per 10 seconds', async () => {
    serve('local')
    renderWithQueryClient(<AuthProvider><Probe /></AuthProvider>)
    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('local:true:true'))
    const before = settingsReads()

    serve('none')
    act(() => {
      staleHandler()()
      staleHandler()()
    })
    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('none:false:false'))
    expect(settingsReads()).toBe(before + 1)

    nowSpy.mockReturnValue(1_000_000 + 9_999)
    await act(async () => staleHandler()())
    expect(settingsReads()).toBe(before + 1)

    nowSpy.mockReturnValue(1_000_000 + 10_000)
    await act(async () => staleHandler()())
    expect(settingsReads()).toBe(before + 2)
  })

  it('unmounting takes the stale-auth handler back', async () => {
    serve('local')
    const { unmount } = renderWithQueryClient(<AuthProvider><Probe /></AuthProvider>)
    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('local:true:true'))
    expect(vi.mocked(setAuthStaleHandler).mock.lastCall?.[0]).toBeTypeOf('function')

    unmount()

    expect(setAuthStaleHandler).toHaveBeenLastCalledWith(null)
  })

  it('a visibility refresh with the same mode does not ask for the user again', async () => {
    serve('local')
    renderWithQueryClient(<AuthProvider><Probe /></AuthProvider>)
    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('local:true:true'))
    const meCalls = () => mockedApi.get.mock.calls.filter(([u]) => u === '/auth/me').length
    const before = meCalls()

    nowSpy.mockReturnValue(1_000_000 + 61_000)
    act(() => {
      Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true })
      document.dispatchEvent(new Event('visibilitychange'))
    })

    await waitFor(() =>
      expect(mockedApi.get.mock.calls.filter(([u]) => u === '/settings/public').length).toBe(2),
    )
    expect(meCalls()).toBe(before)
  })
})
