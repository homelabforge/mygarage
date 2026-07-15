import { createContext, useContext, useState, useEffect, useCallback, ReactNode } from 'react'
import api, { setCSRFToken, getCSRFToken, clearCSRFToken, setApiAuthMode } from '../services/api'

interface User {
  id: number
  username: string
  email: string
  is_admin: boolean
  unit_preference?: 'imperial' | 'metric'
  show_both_units?: boolean
  time_format?: '12h' | '24h'
  mobile_quick_entry_enabled?: boolean
  language?: string
  currency_code?: string
  // Fuel-tracking form defaults (issue #69)
  default_payment_method?: string | null
  default_trip_type?: string | null
}

interface AuthContextType {
  user: User | null
  token: string | null
  isAuthenticated: boolean
  isAdmin: boolean
  loading: boolean
  authMode: string
  login: (username: string, password: string) => Promise<User>
  register: (username: string, email: string, password: string) => Promise<void>
  logout: () => void
  refreshUser: () => Promise<void>
  setAuthToken: (token: string) => void
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

export function AuthProvider({ children }: { children: ReactNode}) {
  const [user, setUser] = useState<User | null>(null)
  const [token, setToken] = useState<string | null>(null) // Token state kept for backward compatibility
  const [loading, setLoading] = useState(true)
  const [authMode, setAuthMode] = useState<string>('none')

  // Logout function - calls backend to clear cookie and CSRF token
  const logout = useCallback(async () => {
    // Clear QE session flag before nulling user so user.id is still available
    if (user?.id) {
      sessionStorage.removeItem(`qe_redirected:${user.id}`)
    }
    try {
      await api.post('/auth/logout')
    } catch (error) {
      console.error('Logout error:', error)
    }
    setToken(null)
    setUser(null)
    clearCSRFToken() // Clear CSRF token on logout (Security Enhancement v2.10.0)
  }, [user])

  // Load user info with proper dependencies (cookie-based auth).
  //
  // Auth mode MUST be resolved from /settings/public BEFORE /auth/me is ever
  // touched. In auth_mode='none' there is no user to load, and probing
  // /auth/me without a cookie returns 401 — which the global response
  // interceptor turns into a hard redirect to /login, bouncing the user off
  // the app (bug #98). A previous revision fired both calls in parallel to
  // shave bootstrap latency; that reintroduced the 401-on-fresh-load redirect,
  // so the gating is deliberate and load-bearing, not an accident. Only load
  // the user when auth is enabled.
  const loadUser = useCallback(async () => {
    try {
      const settingsResponse = await api.get('/settings/public')
      const authModeSetting = settingsResponse.data.settings.find(
        (s: { key: string; value?: string | null }) => s.key === 'auth_mode'
      )
      const fetchedAuthMode = authModeSetting?.value || 'none'
      setAuthMode(fetchedAuthMode)
      // Mirror into the api module so the response interceptor can suppress the
      // /login redirect on 401 when auth is disabled (bug #98).
      setApiAuthMode(fetchedAuthMode)

      // If auth is disabled, skip user loading entirely (no /auth/me probe).
      if (fetchedAuthMode === 'none') {
        return
      }

      // Auth is enabled — load the current user from the cookie session.
      const response = await api.get('/auth/me')
      setUser(response.data)
    } catch (error: unknown) {
      const err = error as { response?: { status?: number } }
      if (err.response?.status === 401) {
        // Cookie expired or invalid
        setUser(null)
        setToken(null)
      }
    } finally {
      setLoading(false)
    }
  }, [])

  // Load user info on mount (cookie-based auth)
  useEffect(() => {
    loadUser()
  }, [loadUser])

  const login = async (username: string, password: string): Promise<User> => {
    try {
      const response = await api.post('/auth/login', { username, password })
      const newToken = response.data.access_token
      const csrfToken = response.data.csrf_token // Security Enhancement v2.10.0

      // Store CSRF token for state-changing requests
      if (csrfToken) {
        setCSRFToken(csrfToken)

        // Verify token was stored successfully
        const storedToken = getCSRFToken()
        if (storedToken !== csrfToken) {
          console.error('[Auth] Failed to store CSRF token in sessionStorage')
          throw new Error('Failed to initialize session. Please try again or check browser settings.')
        }
      }

      // Cookie is set by backend automatically
      // Token state updated for backward compatibility
      setToken(newToken)

      // Load user info — retry once if cookie isn't available yet
      let loadedUser: User
      try {
        const userResponse = await api.get('/auth/me')
        loadedUser = userResponse.data
      } catch {
        // Browser may not have processed Set-Cookie yet; retry after a tick
        await new Promise(resolve => setTimeout(resolve, 50))
        const userResponse = await api.get('/auth/me')
        loadedUser = userResponse.data
      }
      setUser(loadedUser)
      return loadedUser
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } }; message?: string }
      const errorMessage = err.response?.data?.detail || err.message || 'Login failed'
      throw new Error(errorMessage, { cause: error })
    }
  }

  const register = async (username: string, email: string, password: string) => {
    try {
      await api.post('/auth/register', { username, email, password })
      // Registration successful - user needs to login
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } }; message?: string }
      const errorMessage = err.response?.data?.detail || err.message || 'Registration failed'
      throw new Error(errorMessage, { cause: error })
    }
  }

  const refreshUser = useCallback(async () => {
    await loadUser()
  }, [loadUser])

  const setAuthToken = useCallback((newToken: string) => {
    // Cookie is set by backend automatically
    // Token state updated for backward compatibility
    setToken(newToken)
  }, [])

  const value = {
    user,
    token,
    isAuthenticated: !!user,
    isAdmin: user?.is_admin || false,
    loading,
    authMode,
    login,
    register,
    logout,
    refreshUser,
    setAuthToken,
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}
