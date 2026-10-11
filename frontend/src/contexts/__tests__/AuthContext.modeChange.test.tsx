/**
 * Turning sign-in off has to drop the signed-in user, or Share, the account
 * menu and isAdmin stay on screen until a reload, and the server 400s them.
 * Another tab catches up on its next visibility refresh.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, act } from '@testing-library/react'
import { AuthProvider, useAuth } from '../AuthContext'

vi.mock('../../services/api', () => ({
  default: { get: vi.fn(), post: vi.fn() },
  setCSRFToken: vi.fn(),
  getCSRFToken: vi.fn(),
  clearCSRFToken: vi.fn(),
  setApiAuthMode: vi.fn(),
}))

import api, { setApiAuthMode } from '../../services/api'

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

function Probe() {
  const { isAuthenticated, isAdmin, authMode, refreshUser, loading } = useAuth()
  return (
    <div>
      <span data-testid="state">{`${authMode}:${isAuthenticated}:${isAdmin}`}</span>
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
    render(<AuthProvider><Probe /></AuthProvider>)
    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('local:true:true'))

    serve('none')
    screen.getByRole('button').click()

    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('none:false:false'))
  })

  it('a refresh that finds sign-in on tells the api before it asks for the user', async () => {
    serve('none')
    render(<AuthProvider><Probe /></AuthProvider>)
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
    render(<AuthProvider><Probe /></AuthProvider>)
    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('local:true:true'))

    serve('none')
    nowSpy.mockReturnValue(1_000_000 + 61_000)
    act(() => {
      Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true })
      document.dispatchEvent(new Event('visibilitychange'))
    })

    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('none:false:false'))
  })

  it('a visibility refresh with the same mode does not ask for the user again', async () => {
    serve('local')
    render(<AuthProvider><Probe /></AuthProvider>)
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
