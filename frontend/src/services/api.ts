import axios from 'axios'
import {
  parseApiError,
  getErrorMessage,
  getActionErrorMessage,
  shouldRetryRequest,
  isAuthError,
  isPermissionError,
} from '../utils/httpErrorHandler'
import { basePath, withBase } from '../utils/basePath'

const api = axios.create({
  baseURL: withBase('/api'),
  headers: {
    'Content-Type': 'application/json',
  },
  withCredentials: true, // Required for cookie-based authentication
})

// Re-export error utilities for convenience
export {
  parseApiError,
  getErrorMessage,
  getActionErrorMessage,
  shouldRetryRequest,
  isAuthError,
  isPermissionError,
}

// Auth mode mirror — the response interceptor lives outside React and cannot
// read AuthContext, so AuthContext pushes the resolved auth_mode here via
// setApiAuthMode(). It governs whether a 401 should redirect to /login.
let currentAuthMode: string | null = null

export const setApiAuthMode = (mode: string | null): void => {
  currentAuthMode = mode
}

/**
 * Decide whether a 401 response should redirect the browser to /login.
 *
 * In auth_mode='none' there is no login flow, so a 401 — which here means "this
 * endpoint still requires a user" (e.g. /auth/me, widget keys), not "your
 * session expired" — must NOT bounce the user to /login. Doing so stranded
 * auth-disabled users on the login page (bug #98); instead the error surfaces
 * to the caller, which renders an appropriate disabled state. When auth is
 * enabled, an expired/invalid session still redirects, except when already on
 * an auth page.
 */
export function shouldRedirectToLogin(authMode: string | null, pathname: string): boolean {
  if (authMode === 'none') {
    return false
  }
  const base = basePath()
  const p = base && pathname.startsWith(base) ? pathname.slice(base.length) || '/' : pathname
  return p !== '/login' && p !== '/register'
}

// CSRF Token Management (Security Enhancement v2.10.0)
const CSRF_TOKEN_KEY = 'csrf_token'

export const setCSRFToken = (token: string) => {
  sessionStorage.setItem(CSRF_TOKEN_KEY, token)
}

export const getCSRFToken = (): string | null => {
  return sessionStorage.getItem(CSRF_TOKEN_KEY)
}

export const clearCSRFToken = () => {
  sessionStorage.removeItem(CSRF_TOKEN_KEY)
}

// Track CSRF refresh state to prevent multiple simultaneous refreshes
let isRefreshingCSRF = false
let csrfRefreshPromise: Promise<string | null> | null = null

/**
 * Refresh CSRF token from server.
 * This allows recovery when sessionStorage loses the token without requiring re-login.
 * Requires valid JWT cookie to be present.
 */
const refreshCSRFToken = async (): Promise<string | null> => {
  try {
    // Use a fresh axios instance to avoid interceptor recursion
    const response = await axios.get(withBase('/api/auth/csrf-token'), { withCredentials: true })
    const token = response.data.csrf_token
    if (token) {
      setCSRFToken(token)
      console.log('[CSRF] Token refreshed successfully')
      return token
    }
    return null
  } catch (error) {
    console.error('[CSRF] Failed to refresh token:', error)
    return null
  }
}

// Export for use in response interceptor
export { refreshCSRFToken }

// Request interceptor - Add CSRF token to state-changing requests with auto-recovery
api.interceptors.request.use(
  async (config) => {
    // Add CSRF token to POST/PUT/PATCH/DELETE requests
    if (config.method && ['post', 'put', 'patch', 'delete'].includes(config.method.toLowerCase())) {
      let csrfToken = getCSRFToken()

      // If token is missing, try to refresh it (JWT cookie may still be valid)
      if (!csrfToken) {
        console.log('[CSRF] Token missing, attempting refresh...')

        // Prevent multiple simultaneous refresh requests
        if (!isRefreshingCSRF) {
          isRefreshingCSRF = true
          csrfRefreshPromise = refreshCSRFToken()
        }

        // Wait for the refresh to complete
        if (csrfRefreshPromise) {
          csrfToken = await csrfRefreshPromise
        }
        isRefreshingCSRF = false
        csrfRefreshPromise = null
      }

      if (csrfToken) {
        config.headers['X-CSRF-Token'] = csrfToken
      }
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// Response interceptor - Handle 401/403 errors with CSRF recovery
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config

    // Handle 403 CSRF errors with retry
    if (error.response?.status === 403) {
      const detail = error.response?.data?.detail || ''

      // CSRF error - try to recover once before redirecting
      if (detail.includes('CSRF') && !originalRequest._csrfRetried) {
        originalRequest._csrfRetried = true
        console.log('[CSRF] Token invalid/expired, attempting recovery...')

        // Try to get a fresh CSRF token
        const newToken = await refreshCSRFToken()

        if (newToken) {
          // Retry the original request with new token
          originalRequest.headers['X-CSRF-Token'] = newToken
          return api(originalRequest)
        }

        // Recovery failed - redirect to login. Suppressed in auth_mode='none'
        // (same reasoning as the 401 path, bug #98) via shouldRedirectToLogin.
        console.log('[CSRF] Recovery failed, redirecting to login')
        clearCSRFToken()
        if (shouldRedirectToLogin(currentAuthMode, window.location.pathname)) {
          window.location.href = withBase('/login')
        }
      }
    }

    // Handle 401 errors
    if (error.response?.status === 401) {
      // Don't redirect if we're in the OIDC flow (on success page, link account page, or just logged in)
      const base = basePath()
      const raw = window.location.pathname
      const p = base && raw.startsWith(base) ? raw.slice(base.length) || '/' : raw
      const isOIDCFlow = p === '/auth/oidc/success' || p === '/auth/link-account'

      if (!isOIDCFlow) {
        // Cookie is invalid or expired - clear CSRF token and redirect to login.
        // In auth_mode='none' there is no login page to land on, so
        // shouldRedirectToLogin suppresses the bounce (bug #98) and the 401
        // surfaces to the caller instead.
        clearCSRFToken()

        if (shouldRedirectToLogin(currentAuthMode, window.location.pathname)) {
          window.location.href = withBase('/login')
        }
      }
    }

    return Promise.reject(error)
  }
)

export default api
