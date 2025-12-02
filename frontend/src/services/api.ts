import axios from 'axios'
import {
  parseApiError,
  getErrorMessage,
  getActionErrorMessage,
  shouldRetryRequest,
  isAuthError,
  isPermissionError,
} from '../utils/httpErrorHandler'

const api = axios.create({
  baseURL: '/api',
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
    const response = await axios.get('/api/auth/csrf-token', { withCredentials: true })
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

        // Recovery failed - redirect to login
        console.log('[CSRF] Recovery failed, redirecting to login')
        clearCSRFToken()
        if (window.location.pathname !== '/login' && window.location.pathname !== '/register') {
          window.location.href = '/login'
        }
      }
    }

    // Handle 401 errors
    if (error.response?.status === 401) {
      // Don't redirect if we're in the OIDC flow (on success page, link account page, or just logged in)
      const isOIDCFlow = window.location.pathname === '/auth/oidc/success' ||
                         window.location.pathname === '/auth/link-account'

      if (!isOIDCFlow) {
        // Cookie is invalid or expired - clear CSRF token and redirect to login
        clearCSRFToken()

        // Redirect to login page if not already there
        if (window.location.pathname !== '/login' && window.location.pathname !== '/register') {
          window.location.href = '/login'
        }
      }
    }

    return Promise.reject(error)
  }
)

export default api
