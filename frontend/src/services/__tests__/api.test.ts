import { describe, it, expect, beforeEach } from 'vitest'
import { shouldRedirectToLogin } from '../api'

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
