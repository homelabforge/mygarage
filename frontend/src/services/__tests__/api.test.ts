import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import axios, { AxiosError, type AxiosAdapter, type AxiosResponse } from 'axios'
import api, { setApiAuthMode, setAuthStaleHandler, setCSRFToken, shouldRedirectToLogin } from '../api'

// setup.ts stubs axios out; the interceptor cases need the real one. Every
// request below brings its own adapter, so nothing goes on the wire.
vi.unmock('axios')

function setBase(href: string) {
  document.head.querySelector('base')?.remove()
  const el = document.createElement('base')
  el.setAttribute('href', href)
  document.head.appendChild(el)
}

describe('shouldRedirectToLogin', () => {
  it('does not redirect to /login when auth_mode is none (bug #98)', () => {
    // In auth_mode='none' there is no login page to land on. A 401 from an
    // endpoint that still requires a user (e.g. /auth/me, widget keys) must
    // not bounce the user to /login — it should surface to the caller, which
    // renders an appropriate disabled state.
    expect(shouldRedirectToLogin('none', '/')).toBe(false)
    expect(shouldRedirectToLogin('none', '/settings')).toBe(false)
  })

  it('redirects to /login on 401 when auth is enabled', () => {
    expect(shouldRedirectToLogin('local', '/')).toBe(true)
    expect(shouldRedirectToLogin('oidc', '/settings')).toBe(true)
  })

  it('does not redirect when already on an auth page', () => {
    expect(shouldRedirectToLogin('local', '/login')).toBe(false)
    expect(shouldRedirectToLogin('local', '/register')).toBe(false)
  })

  it('redirects when auth mode is not yet known (preserves default behavior)', () => {
    // Before AuthContext mirrors the mode into the api module, currentAuthMode
    // is null. Falling back to "redirect" matches pre-fix behavior for
    // authenticated deployments, so an expired session still lands on /login.
    expect(shouldRedirectToLogin(null, '/')).toBe(true)
  })
})

describe('shouldRedirectToLogin under a subpath', () => {
  beforeEach(() => setBase('/mygarage/'))

  it('treats /mygarage/login as the login page (no redirect loop)', () => {
    expect(shouldRedirectToLogin('local', '/mygarage/login')).toBe(false)
  })

  it('still redirects from an app route under the prefix', () => {
    expect(shouldRedirectToLogin('local', '/mygarage/vehicles')).toBe(true)
  })
})

// An adapter that answers every request with this status and body, so the
// real response interceptor sees it.
function answer(status: number, data: unknown): AxiosAdapter {
  return (config) => {
    const response = { status, statusText: '', headers: {}, config, data } as AxiosResponse
    return Promise.reject(new AxiosError('refused', 'ERR_BAD_REQUEST', config, null, response))
  }
}

const SIGN_IN = { detail: { detail: 'requires_sign_in', message: 'Sharing requires auth_mode=local or oidc.' } }

describe('a refused write tells a stale tab that auth is off', () => {
  beforeEach(() => {
    // A token on hand, so the write doesn't go looking for one.
    setCSRFToken('token')
  })

  afterEach(() => {
    setAuthStaleHandler(null)
    setApiAuthMode(null)
    sessionStorage.clear()
  })

  it('calls the handler once when this tab still thinks auth is on', async () => {
    const handler = vi.fn()
    setAuthStaleHandler(handler)
    setApiAuthMode('local')

    const write = api.post('/vehicles/1/shares', {}, { adapter: answer(400, SIGN_IN) })

    await expect(write).rejects.toMatchObject({ response: { status: 400, data: SIGN_IN } })
    expect(handler).toHaveBeenCalledTimes(1)
  })

  it('leaves the handler alone when this tab already knows auth is off', async () => {
    const handler = vi.fn()
    setAuthStaleHandler(handler)
    setApiAuthMode('none')

    await expect(api.post('/x', {}, { adapter: answer(400, SIGN_IN) })).rejects.toBeInstanceOf(AxiosError)
    expect(handler).not.toHaveBeenCalled()
  })

  it('ignores any other 400', async () => {
    const handler = vi.fn()
    setAuthStaleHandler(handler)
    setApiAuthMode('local')

    const other = { detail: { detail: 'something_else', message: 'nope' } }
    await expect(api.post('/x', {}, { adapter: answer(400, other) })).rejects.toBeInstanceOf(AxiosError)
    await expect(api.post('/x', {}, { adapter: answer(400, { detail: 'requires_sign_in' }) })).rejects.toBeInstanceOf(AxiosError)
    await expect(api.post('/x', {}, { adapter: answer(422, SIGN_IN) })).rejects.toBeInstanceOf(AxiosError)
    expect(handler).not.toHaveBeenCalled()
  })

  it('still rejects with the original error when no handler is set', async () => {
    setApiAuthMode('local')
    const logged = vi.spyOn(console, 'error').mockImplementation(() => {})
    try {
      await expect(api.post('/x', {}, { adapter: answer(400, SIGN_IN) })).rejects.toMatchObject({
        response: { status: 400, data: SIGN_IN },
      })
      // No handler means nothing to call, not a swallowed TypeError.
      expect(logged).not.toHaveBeenCalled()
    } finally {
      logged.mockRestore()
    }
  })

  it('a handler that throws still hands back the original 400', async () => {
    const handler = vi.fn(() => {
      throw new Error('handler blew up')
    })
    setAuthStaleHandler(handler)
    setApiAuthMode('local')
    const logged = vi.spyOn(console, 'error').mockImplementation(() => {})
    try {
      await expect(api.post('/x', {}, { adapter: answer(400, SIGN_IN) })).rejects.toMatchObject({
        response: { status: 400, data: SIGN_IN },
      })
      expect(handler).toHaveBeenCalledTimes(1)
      // The catch said what broke, with the handler's own error.
      expect(logged).toHaveBeenCalledTimes(1)
      expect(logged).toHaveBeenCalledWith('[Auth] Stale-auth handler failed:', expect.objectContaining({ message: 'handler blew up' }))
    } finally {
      logged.mockRestore()
    }
  })
})

describe('a stalled CSRF fetch never outlasts the write waiting on it', () => {
  afterEach(() => {
    vi.useRealTimers()
    setApiAuthMode(null)
    sessionStorage.clear()
  })

  it('the write still fails inside its own deadline', async () => {
    vi.useFakeTimers()
    setApiAuthMode('none')
    sessionStorage.clear()
    // The token fetch goes through bare axios. This one never answers, and like
    // the real adapter it only gives up when the request carries a timeout.
    const stall: AxiosAdapter = (config) =>
      new Promise((_resolve, reject) => {
        if (config.timeout) {
          setTimeout(() => reject(new AxiosError('timeout', 'ECONNABORTED', config)), config.timeout)
        }
      })
    const bareAdapter = axios.defaults.adapter
    axios.defaults.adapter = stall
    const logged = vi.spyOn(console, 'error').mockImplementation(() => {})
    const noise = vi.spyOn(console, 'log').mockImplementation(() => {})
    try {
      let outcome: unknown = 'pending'
      api
        .patch('/x', {}, { timeout: 30_000, adapter: answer(403, { detail: 'CSRF token missing' }) })
        .then(
          () => (outcome = 'resolved'),
          (error: unknown) => (outcome = error)
        )

      await vi.advanceTimersByTimeAsync(30_000)

      expect(outcome).toMatchObject({ response: { status: 403 } })
    } finally {
      axios.defaults.adapter = bareAdapter
      logged.mockRestore()
      noise.mockRestore()
    }
  })
})
