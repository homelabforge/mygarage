import { createContext, useContext, useState, useEffect, useCallback, ReactNode } from 'react'
import api, { setCSRFToken, getCSRFToken, clearCSRFToken, setApiAuthMode } from '../services/api'
import type { components } from '../types/api.generated'
import type { UnitSet } from '../types/units'
import { readPublicUnitDefaults, type PublicSetting } from '../utils/publicUnitDefaults'

/**
 * The user shape comes from the generated schema, not from a hand-maintained
 * interface. The previous local interface declared
 * `unit_preference?: 'imperial' | 'metric'` and drifted silently: the API
 * freshness gate diffs the generated file, so nothing was watching this one.
 * Migration 093 can now write 'custom', a value that union never admitted.
 */
type User = components['schemas']['UserResponse']

interface AuthContextType {
  user: User | null
  token: string | null
  isAuthenticated: boolean
  isAdmin: boolean
  loading: boolean
  authMode: string
  /**
   * The instance-wide default unit set from `/settings/public`, or null when
   * the instance published none this client could parse.
   *
   * Second rung of the unit precedence: an authenticated account's
   * `resolved_units` outrank it, and it outranks the browser-owned legacy
   * localStorage keys. See `useUnitPreference`.
   */
  defaultUnitPrefs: UnitSet | null
  /**
   * Whether `/settings/public` has actually resolved at least once.
   *
   * ★ IT SEPARATES "THE ROW IS ABSENT" FROM "WE NEVER GOT AN ANSWER", which
   * `defaultUnitPrefs === null` alone cannot: the fetch failing and the row
   * being missing or unparseable both land on null. That distinction is
   * load-bearing for a WRITER. `InstanceUnitDefaultsCard` falls back to the
   * imperial preset when it has no published set, which is the right thing to
   * DISPLAY (the server falls back the same way) and the wrong thing to be able
   * to SAVE: its Custom button fires immediately, with no confirmation, so an
   * admin on a UK or metric instance whose boot fetch failed could write US
   * imperial as the instance-wide default for everyone by opening a grid.
   *
   * Never returns to false once true. A later `refreshUser` that fails leaves
   * the last good answer in place rather than blanking a control mid-session,
   * which is the same rule `defaultUnitPrefs` itself follows.
   */
  publicSettingsLoaded: boolean
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
  const [defaultUnitPrefs, setDefaultUnitPrefs] = useState<UnitSet | null>(null)
  const [publicSettingsLoaded, setPublicSettingsLoaded] = useState(false)

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
      const publicSettings: PublicSetting[] = settingsResponse.data?.settings ?? []

      // Read BEFORE the auth_mode short-circuit below, not after. auth_mode
      // 'none' is the one mode with no user to carry a unit preference, so it
      // is the mode that needs the instance default most, and returning early
      // first is exactly why four phases shipped with this payload discarded.
      setDefaultUnitPrefs(readPublicUnitDefaults(publicSettings))
      // Set from the same payload and in the same order, so nothing can observe
      // "loaded" while `defaultUnitPrefs` still holds the previous answer.
      setPublicSettingsLoaded(true)

      const authModeSetting = publicSettings.find((s) => s.key === 'auth_mode')
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

  // Login/register deliberately do NOT catch-and-rewrap. The original AxiosError
  // (with its `.response.data.detail` — an array on a 422) has to reach the
  // caller intact: Login.tsx/Register.tsx call `applyServerErrors`, which needs
  // a real AxiosError for `parseApiError` to populate `fieldErrors`. Collapsing
  // it to `new Error(string)` here previously (a) stringified a 422's array
  // detail into literal "[object Object],[object Object]" text, and (b) made
  // the per-field error path permanently dead code, since `parseApiError` only
  // parses `fieldErrors` from a real AxiosError.
  const login = async (username: string, password: string): Promise<User> => {
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
  }

  const register = async (username: string, email: string, password: string) => {
    await api.post('/auth/register', { username, email, password })
    // Registration successful - user needs to login
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
    defaultUnitPrefs,
    publicSettingsLoaded,
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
