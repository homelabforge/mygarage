import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render } from '../../__tests__/test-utils'

const h = vi.hoisted(() => ({
  get: vi.fn(),
  setCSRFToken: vi.fn(),
}))

vi.mock('../../services/api', () => ({
  default: { get: h.get },
  setCSRFToken: h.setCSRFToken,
}))

import OIDCSuccess from '../OIDCSuccess'

// What React Router keeps in history.state. The strip has to leave it alone.
const ROUTER_STATE = { usr: null, key: 'sso', idx: 0 }

// Where the callback's 302 lands: the token is in the fragment, never the query.
function arriveAt(url: string): void {
  window.history.replaceState(ROUTER_STATE, '', url)
}

beforeEach(() => {
  // The redirect waits 300ms and then does a full-page navigate, which jsdom
  // can't do. Nothing here moves the clock, so it never fires.
  vi.useFakeTimers()
})

afterEach(() => {
  vi.clearAllTimers()
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.clearAllMocks()
  window.history.replaceState(null, '', '/')
})

describe('OIDCSuccess: the CSRF token rides in the fragment', () => {
  it('stores the CSRF token from the hash, then strips it', () => {
    arriveAt('/auth/oidc/success#csrf_token=csrf-abc')
    const strip = vi.spyOn(window.history, 'replaceState')

    render(<OIDCSuccess />)

    expect(h.setCSRFToken).toHaveBeenCalledWith('csrf-abc')
    expect(strip).toHaveBeenCalledWith(ROUTER_STATE, '', '/auth/oidc/success')
    expect(window.location.pathname).toBe('/auth/oidc/success')
    expect(window.location.hash).toBe('')
    expect(window.history.state).toEqual(ROUTER_STATE)
  })

  it('stores it once under StrictMode, whose second pass finds no hash', () => {
    arriveAt('/auth/oidc/success#csrf_token=csrf-abc')

    // StrictMode wraps the router, as in main.tsx. Nested under a provider that
    // mounts with it, React 19 never runs the effects twice.
    render(<OIDCSuccess />, { reactStrictMode: true })

    expect(h.setCSRFToken.mock.calls).toEqual([['csrf-abc']])
    expect(window.location.hash).toBe('')
  })
})
