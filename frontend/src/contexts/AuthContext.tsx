import { createContext, useContext, useState, useEffect, useCallback, useRef, ReactNode } from 'react'
import { hashKey, useQueryClient } from '@tanstack/react-query'
import api, { setCSRFToken, getCSRFToken, clearCSRFToken, setApiAuthMode } from '../services/api'
import { fetchPublicSettingRows, publicSettingsQuery } from '../hooks/queries/usePublicSettings'
import type { components } from '../types/api.generated'
import type { UnitSet } from '../types/units'
import { readPublicUnitDefaults, type PublicSetting } from '../utils/publicUnitDefaults'
import { readPublicDefaultCountry } from '../utils/publicCountryDefault'
import { setHouseholdTimeZone } from '../constants/i18n'
import { analyticsCacheOwner, type AnalyticsCacheOwner } from '../utils/analyticsCache'
import { claimOfflineData, forgetOfflineData, releaseOfflineData, watchOfflineOwner } from '../utils/offlineData'

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
  /**
   * The instance's `default_country` from `/settings/public` (ISO 3166-1
   * alpha-2), or null when none is set. Last rung of the country precedence:
   * a vehicle's registration country, then the account's country, then this.
   * See `useResolvedCountry`.
   */
  defaultCountry: string | null
  login: (username: string, password: string) => Promise<User>
  register: (username: string, email: string, password: string) => Promise<void>
  /**
   * Sign out. Resolves false when the server couldn't be told, and then
   * nothing changes: only the server can clear the session cookie.
   */
  logout: () => Promise<boolean>
  refreshUser: () => Promise<void>
  /**
   * Refetch `/settings/public` and update the stores it feeds (the shared
   * query every reader selects from, the instance unit defaults and the
   * household time zone). The Settings page awaits it after every save; the
   * Backup tab after a restore; every client calls it on `visibilitychange`,
   * rate-limited.
   */
  refreshPublicSettings: () => Promise<void>
  /**
   * The household time zone from `/settings/public` as REACT STATE, so a
   * consumer (the calendar) re-renders when a refresh changes it. The
   * module-level store in constants/i18n serves non-React code; this mirrors
   * it.
   */
  householdTimeZone: string | null
  setAuthToken: (token: string) => void
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

export function AuthProvider({ children }: { children: ReactNode}) {
  const [user, setUser] = useState<User | null>(null)
  const [token, setToken] = useState<string | null>(null) // Token state kept for backward compatibility
  const [loading, setLoading] = useState(true)
  const [authMode, setAuthMode] = useState<string>('none')
  const [defaultUnitPrefs, setDefaultUnitPrefs] = useState<UnitSet | null>(null)
  const [defaultCountry, setDefaultCountry] = useState<string | null>(null)
  const [publicSettingsLoaded, setPublicSettingsLoaded] = useState(false)
  // The tree's client, not the module one, so a test's cache is the one used.
  const queryClient = useQueryClient()

  // loadUser's read: a real request unless one is already out (staleTime 0),
  // and it throws on failure so loadUser's catch still runs. No retry: a failed
  // boot read must reach that catch now, not a second later.
  const fetchPublicSettings = useCallback(
    () => queryClient.fetchQuery({ ...publicSettingsQuery, staleTime: 0, retry: false }),
    [queryClient],
  )

  // Bumped by every logout. A load or login that started before one is stale
  // and mustn't put anybody back.
  const authGenRef = useRef(0)
  // Whose data the query cache holds, so a different account can't read it.
  const cacheOwnerRef = useRef<AnalyticsCacheOwner>(null)
  // A second click on Sign out joins the first instead of posting again.
  const logoutInFlightRef = useRef<Promise<boolean> | null>(null)

  // Logout function - calls backend to clear cookie and CSRF token
  const logout = useCallback((): Promise<boolean> => {
    if (logoutInFlightRef.current) return logoutInFlightRef.current
    authGenRef.current += 1
    const run = async (): Promise<boolean> => {
      try {
        await api.post('/auth/logout')
      } catch (error: unknown) {
        // Only the server can clear the HttpOnly cookie. If it never heard us,
        // we're still signed in, and pretending otherwise hands the browser back
        // to this account once it's online. A 401 means the session's gone already.
        if ((error as { response?: { status?: number } }).response?.status !== 401) {
          console.error('Logout error:', error)
          return false
        }
      }
      // Clear QE session flag before nulling user so user.id is still available
      if (user?.id) {
        sessionStorage.removeItem(`qe_redirected:${user.id}`)
      }
      setToken(null)
      setUser(null)
      clearCSRFToken() // Clear CSRF token on logout (Security Enhancement v2.10.0)
      // The next account on this browser mustn't find any of this one's data.
      // Marker first, so a tab closed halfway leaves copies nobody owns.
      releaseOfflineData()
      queryClient.clear()
      cacheOwnerRef.current = null
      await forgetOfflineData()
      return true
    }
    const pending = run().finally(() => {
      logoutInFlightRef.current = null
    })
    logoutInFlightRef.current = pending
    return pending
  }, [user, queryClient])

  // Every place a user gets set goes through here, so the offline copies are
  // claimed for that account before any page can read them. `gen` is the
  // logout count when the caller started, and `current` is asked after the
  // claim, since the await can outlive the reason for setting this user.
  const adoptUser = useCallback(
    async (
      owner: AnalyticsCacheOwner,
      next: User | null,
      gen: number,
      current: () => boolean = () => true,
    ): Promise<void> => {
      // A logout landed since this started, so this answer is about a session that's over.
      if (gen !== authGenRef.current) return
      await claimOfflineData(owner)
      if (gen !== authGenRef.current || !current()) return
      // Another account's pages are still in memory. Drop them before anyone
      // renders. The public settings aren't anyone's, and a mode switch just wrote them.
      if (cacheOwnerRef.current !== null && owner !== null && owner !== cacheOwnerRef.current) {
        const shared = hashKey(publicSettingsQuery.queryKey)
        queryClient.removeQueries({ predicate: (query) => query.queryHash !== shared })
      }
      if (owner !== null) cacheOwnerRef.current = owner
      setUser(next)
    },
    [queryClient],
  )

  // Another tab signed out or in as someone else: this one's showing a
  // session that's gone, so start over from the server.
  useEffect(
    () =>
      watchOfflineOwner((next) => {
        if (next !== cacheOwnerRef.current) window.location.reload()
      }),
    [],
  )

  // The mode the client last loaded, so a background refresh can spot a change.
  // Null until a load records one: a refresh that beats boot's read has nothing
  // to compare against, and treating that as 'none' loaded the user twice.
  const authModeRef = useRef<string | null>(null)
  // How many loadUser calls are still out, so a refresh knows whether one of
  // them is going to record the mode.
  const loadsInFlightRef = useRef(0)
  const lastPublicRefreshRef = useRef(0)
  const [householdTimeZone, setHouseholdTimeZoneState] = useState<string | null>(null)

  // Every /settings/public read gets a place in line when it goes out, and only
  // the newest answer so far is used. Answers can land in any order, and a
  // fetchQuery can join a read some page sent before a refresh did.
  const readOrderRef = useRef(0)
  const readPlacesRef = useRef(new WeakMap<Promise<unknown>, number>())
  const appliedRef = useRef<{ place: number; rows: PublicSetting[] } | null>(null)

  // The shared query's read that's out right now, if any. Paused counts too: an
  // offline read resumes later and can land after a newer one.
  const pendingQueryRead = useCallback((): Promise<unknown> | undefined => {
    const query = queryClient
      .getQueryCache()
      .find({ queryKey: publicSettingsQuery.queryKey, exact: true })
    return query && query.state.fetchStatus !== 'idle' ? query.promise : undefined
  }, [queryClient])

  // Feeds the stores from these rows unless a later read already did, and hands
  // back whichever rows are current now.
  const applyPublicSettings = useCallback(
    (rows: PublicSetting[], place: number): PublicSetting[] => {
      const applied = appliedRef.current
      if (applied && applied.place > place) return applied.rows
      appliedRef.current = { place, rows }
      // Read BEFORE the auth_mode short-circuit in loadUserFor, not after.
      // auth_mode 'none' is the one mode with no user to carry a unit
      // preference, so it is the mode that needs the instance default most.
      setDefaultUnitPrefs(readPublicUnitDefaults(rows))
      setDefaultCountry(readPublicDefaultCountry(rows))
      const zone = rows.find((s) => s.key === 'effective_timezone')?.value ?? null
      setHouseholdTimeZone(zone)
      setHouseholdTimeZoneState(zone)
      lastPublicRefreshRef.current = Date.now()
      // Set from the same payload and in the same order, so nothing can observe
      // "loaded" while `defaultUnitPrefs` still holds the previous answer.
      setPublicSettingsLoaded(true)
      return rows
    },
    [],
  )

  // Records the mode these rows carry, then loads the user for it.
  //
  // Auth mode MUST be resolved from /settings/public BEFORE /auth/me is ever
  // touched. In auth_mode='none' there is no user to load, and probing
  // /auth/me without a cookie returns 401, which the global response
  // interceptor turns into a hard redirect to /login, bouncing the user off
  // the app (bug #98). A previous revision fired both calls in parallel to
  // shave bootstrap latency; that reintroduced the 401-on-fresh-load redirect,
  // so the gating is deliberate and load-bearing, not an accident.
  const loadUserFor = useCallback(async (rows: PublicSetting[]): Promise<void> => {
    const gen = authGenRef.current
    const mode = rows.find((s) => s.key === 'auth_mode')?.value || 'none'
    authModeRef.current = mode
    setAuthMode(mode)
    // Mirror into the api module so the response interceptor can suppress the
    // /login redirect on 401 when auth is disabled (bug #98).
    setApiAuthMode(mode)

    // If auth is disabled, skip user loading entirely (no /auth/me probe).
    // A user left over from before sign-in was turned off means nothing now.
    // The copies belong to the open instance then, so they're claimed as 'local'.
    if (mode === 'none') {
      setToken(null)
      // A newer load that turned sign-in back on owns the user now.
      await adoptUser(analyticsCacheOwner(mode, null), null, gen, () => authModeRef.current === 'none')
      return
    }

    try {
      const response = await api.get('/auth/me')
      const loaded: User = response.data
      // Claimed before the check below, so the await can't sneak past it.
      // Sign-in got turned off while this was out, so there's no one to show.
      await adoptUser(analyticsCacheOwner(mode, loaded.id), loaded, gen, () => authModeRef.current !== 'none')
    } catch (error: unknown) {
      const err = error as { response?: { status?: number } }
      if (err.response?.status === 401) {
        // Cookie expired or invalid
        setUser(null)
        setToken(null)
      }
    }
  }, [adoptUser])

  // Load user info (cookie-based auth): public settings first, then the user.
  const loadUser = useCallback(async () => {
    loadsInFlightRef.current += 1
    try {
      const answer = fetchPublicSettings()
      // fetchQuery may have joined a read that was already out. A refresh gives
      // whatever is out a place when it starts, so a read with no place yet
      // went out after every refresh so far.
      const read = pendingQueryRead()
      let place = read ? readPlacesRef.current.get(read) : undefined
      if (place === undefined) {
        place = ++readOrderRef.current
        if (read) readPlacesRef.current.set(read, place)
      }
      const rows = applyPublicSettings(await answer, place)
      await loadUserFor(rows)
    } catch {
      // The public settings read failed: keep whatever is showing. A refresh
      // that lands later loads the user then. One that already landed left
      // the user to us, so load it from that refresh's rows.
      const applied = appliedRef.current
      if (applied && authModeRef.current === null) await loadUserFor(applied.rows)
    } finally {
      loadsInFlightRef.current -= 1
      setLoading(false)
    }
  }, [applyPublicSettings, fetchPublicSettings, loadUserFor, pendingQueryRead])

  // Load user info on mount (cookie-based auth)
  useEffect(() => {
    loadUser()
  }, [loadUser])

  // Its own GET, never fetchQuery: a refresh after a save has to show the save,
  // and fetchQuery would hand back a read that was already out. Throws like
  // fetchQuery, so the catch below still keeps the current values.
  const refreshPublicSettings = useCallback(async () => {
    try {
      const key = publicSettingsQuery.queryKey
      // A read that's already out went out before this one.
      const older = pendingQueryRead()
      if (older && !readPlacesRef.current.has(older)) {
        readPlacesRef.current.set(older, ++readOrderRef.current)
      }
      const place = ++readOrderRef.current
      const fetched = await fetchPublicSettingRows()
      const rows = applyPublicSettings(fetched, place)
      // A newer read already landed, filled the cache and loaded the user.
      if (rows !== fetched) return
      queryClient.setQueryData(key, rows)
      // That older read can land after this one and put its answer back.
      if (older) {
        void older.then(
          () => {
            const latest = appliedRef.current
            if (latest) queryClient.setQueryData(key, latest.rows)
          },
          () => {},
        )
      }
      const mode = rows.find((s) => s.key === 'auth_mode')?.value || 'none'
      const known = authModeRef.current
      // No mode yet while boot's load is still out: it records one and loads
      // the user itself. With none out (boot failed) this is the first answer.
      const reload = known === null ? loadsInFlightRef.current === 0 : mode !== known
      if (reload) {
        // Sign-in got turned on or off somewhere else: reload who's signed in,
        // from these rows. Reading again could join that older read.
        await loadUserFor(rows)
      }
    } catch {
      // Keep the current values. The server stays authoritative for every
      // date it fills in or judges; the browser catches up on the next
      // successful refetch or reload.
    }
  }, [applyPublicSettings, loadUserFor, pendingQueryRead, queryClient])

  // Another client (or a restore) can change the household zone while this
  // tab sits in the background: refetch when the document becomes visible,
  // at most once per 60 seconds (plan 4.5.1).
  useEffect(() => {
    const onVisibilityChange = () => {
      if (document.visibilityState !== 'visible') return
      if (Date.now() - lastPublicRefreshRef.current < 60_000) return
      // Stamp before the async call so a second event in the same tick
      // cannot pass the check while the first fetch is still in flight.
      lastPublicRefreshRef.current = Date.now()
      void refreshPublicSettings()
    }
    document.addEventListener('visibilitychange', onVisibilityChange)
    return () => document.removeEventListener('visibilitychange', onVisibilityChange)
  }, [refreshPublicSettings])

  // Login/register deliberately do NOT catch-and-rewrap. The original AxiosError
  // (with its `.response.data.detail` — an array on a 422) has to reach the
  // caller intact: Login.tsx/Register.tsx call `applyServerErrors`, which needs
  // a real AxiosError for `parseApiError` to populate `fieldErrors`. Collapsing
  // it to `new Error(string)` here previously (a) stringified a 422's array
  // detail into literal "[object Object],[object Object]" text, and (b) made
  // the per-field error path permanently dead code, since `parseApiError` only
  // parses `fieldErrors` from a real AxiosError.
  const login = async (username: string, password: string): Promise<User> => {
    const gen = authGenRef.current
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
    // Form login never goes through loadUser, so it claims here.
    await adoptUser(analyticsCacheOwner(authModeRef.current ?? 'local', loadedUser.id), loadedUser, gen)
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
    defaultCountry,
    publicSettingsLoaded,
    login,
    register,
    logout,
    refreshUser,
    refreshPublicSettings,
    householdTimeZone,
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
