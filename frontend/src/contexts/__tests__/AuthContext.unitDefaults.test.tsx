/**
 * `/settings/public` has published a resolved unit set for clients with no user
 * since phase 1 and `AuthContext` threw it away, so an anonymous visitor on a
 * metric-default instance rendered IMPERIAL.
 *
 * Two properties are pinned here, and the first is the one that made the bug
 * survive four phases: `loadUser` returns early when `auth_mode === 'none'`, so
 * the one mode that has no user to carry a preference is the mode that never
 * reached the parse. The default must therefore be read BEFORE that return.
 *
 * The second is that the instance default is a DEFAULT: it answers for a
 * browser that has never chosen, and loses to one that has. Both halves are
 * tested here, because getting that ordering wrong makes metric unreachable on
 * an `auth_mode=none` instance (migration 093 seeds imperial or UK-imperial and
 * never metric, and the browser key is the only units control such an instance
 * has).
 *
 * These tests drive the REAL AuthProvider and the REAL useUnitPreference, with
 * only the HTTP layer mocked, so they prove the wiring end to end rather than
 * agreeing with a mocked context.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { makeUser } from '@/__tests__/factories'
import { AuthProvider, useAuth } from '../AuthContext'
import { useUnitPreference } from '@/hooks/useUnitPreference'

/**
 * Let the browser preference store re-read `localStorage`.
 *
 * Rung 2 is the `unit_prefs` store since phase 4 task 3, and it parses once at
 * module load, so a `setItem` in a test body is invisible to it without the
 * `storage` event production uses. The legacy `unit_preference` key each test
 * below writes still reaches the hook, through the store's one-shot migration.
 */
function reloadBrowserPrefs(): void {
  window.dispatchEvent(new Event('storage'))
}

vi.mock('../../services/api', () => {
  const mockApi = {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
    interceptors: {
      request: { use: vi.fn() },
      response: { use: vi.fn() },
    },
    defaults: { headers: { common: {} } },
  }
  return {
    default: mockApi,
    setCSRFToken: vi.fn(),
    getCSRFToken: vi.fn(),
    clearCSRFToken: vi.fn(),
    setApiAuthMode: vi.fn(),
  }
})

import api from '../../services/api'

const mockedApi = vi.mocked(api)

/** METRIC_PRESET, exactly as `/api/settings/public` serves it. */
const METRIC_RAW =
  '{"consumption": "l_100km", "distance": "km", "length": "m", "mass": "kg", "pressure": "kpa", "secondary_gallon": "us", "speed": "kmh", "temperature": "c", "torque": "nm", "tread": "mm", "volume": "L"}'

/** UK_IMPERIAL_PRESET (migration 093's UK_IMPERIAL_SET), as served. */
const UK_IMPERIAL_RAW =
  '{"consumption": "mpg_uk", "distance": "mi", "length": "ft", "mass": "lb", "pressure": "psi", "secondary_gallon": "uk", "speed": "mph", "temperature": "f", "torque": "lbft", "tread": "in32", "volume": "gal_uk"}'

function Consumer() {
  const { defaultUnitPrefs, loading, authMode, publicSettingsLoaded } = useAuth()
  const { system, gallonStandard } = useUnitPreference()
  return (
    <div>
      <span data-testid="loading">{String(loading)}</span>
      <span data-testid="auth-mode">{authMode}</span>
      <span data-testid="defaults-present">{String(defaultUnitPrefs !== null)}</span>
      <span data-testid="public-loaded">{String(publicSettingsLoaded)}</span>
      <span data-testid="defaults-volume">{defaultUnitPrefs?.volume ?? 'none'}</span>
      <span data-testid="defaults-distance">{defaultUnitPrefs?.distance ?? 'none'}</span>
      <span data-testid="defaults-pressure">{defaultUnitPrefs?.pressure ?? 'none'}</span>
      <span data-testid="defaults-secondary-gallon">
        {defaultUnitPrefs?.secondary_gallon ?? 'none'}
      </span>
      <span data-testid="system">{system}</span>
      <span data-testid="gallon-standard">{gallonStandard}</span>
    </div>
  )
}

function mountWithPublicSettings(settings: Array<{ key: string; value?: string | null }>) {
  mockedApi.get.mockImplementation((url: string) => {
    if (url === '/settings/public') return Promise.resolve({ data: { settings } })
    if (url === '/auth/me') return Promise.reject({ response: { status: 401 } })
    return Promise.reject(new Error('unexpected url'))
  })
  render(
    <AuthProvider>
      <Consumer />
    </AuthProvider>
  )
}

describe('AuthContext default_unit_prefs', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // ★ A pin on the gallon store used to sit here, so a 'uk' answer below could
    // only have come from the payload. Phase 4 task 5 retired that store; the
    // `localStorage.clear()` below now covers the same ground, because the only
    // surviving reader of `imperial_gallon_standard` is the browser store's
    // one-shot legacy migration.
    localStorage.clear()
    sessionStorage.clear()
    reloadBrowserPrefs()
  })

  it('parses the default before the auth_mode=none early return', async () => {
    mountWithPublicSettings([
      { key: 'auth_mode', value: 'none' },
      { key: 'default_unit_prefs', value: METRIC_RAW },
    ])

    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('false')
    })
    expect(screen.getByTestId('auth-mode')).toHaveTextContent('none')
    expect(screen.getByTestId('defaults-present')).toHaveTextContent('true')
    expect(screen.getByTestId('defaults-volume')).toHaveTextContent('L')
    expect(screen.getByTestId('defaults-distance')).toHaveTextContent('km')
    expect(screen.getByTestId('defaults-pressure')).toHaveTextContent('kpa')
    expect(screen.getByTestId('defaults-secondary-gallon')).toHaveTextContent('us')
    // /auth/me is still never probed: bug #98's guard is untouched.
    const requestedUrls = mockedApi.get.mock.calls.map((call: unknown[]) => call[0])
    expect(requestedUrls).not.toContain('/auth/me')
  })

  it('★ separates a row that is absent from a payload that never arrived', async () => {
    // ★ TWO STATES THAT `defaultUnitPrefs === null` CANNOT TELL APART, and a
    // WRITER has to. A missing or unparseable row is a configured instance
    // falling back the way `parse_default_unit_prefs` does on the server; a
    // failed fetch is an instance whose real default is unknown, and
    // `authMode` is still sitting on its 'none' initial value, so the admin
    // gate `InstanceUnitDefaultsCard` uses reads OPEN. Writing the displayed
    // imperial fallback back as the instance default would be a 20 percent
    // error published for every client, chosen by nobody.
    mockedApi.get.mockImplementation((url: string) => {
      if (url === '/settings/public') return Promise.reject(new Error('network down'))
      return Promise.reject(new Error('unexpected url'))
    })
    render(
      <AuthProvider>
        <Consumer />
      </AuthProvider>
    )

    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('false')
    })
    expect(screen.getByTestId('public-loaded')).toHaveTextContent('false')
    expect(screen.getByTestId('defaults-present')).toHaveTextContent('false')
    // The gate really is open on this path, which is why the flag is needed.
    expect(screen.getByTestId('auth-mode')).toHaveTextContent('none')
  })

  it('★ and reports the payload as loaded when it arrives without the row', async () => {
    // The mirror. Same null `defaultUnitPrefs`, opposite answer, so neither
    // case can pass on a flag wired to the wrong thing.
    mountWithPublicSettings([{ key: 'auth_mode', value: 'none' }])

    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('false')
    })
    expect(screen.getByTestId('public-loaded')).toHaveTextContent('true')
    expect(screen.getByTestId('defaults-present')).toHaveTextContent('false')
  })

  it('an anonymous visitor who never chose gets the metric instance default', async () => {
    // The shipped defect, end to end: no browser key, so the instance default
    // answers. Before this change the same render produced imperial.
    expect(localStorage.getItem('unit_preference')).toBeNull()

    mountWithPublicSettings([
      { key: 'auth_mode', value: 'local' },
      { key: 'default_unit_prefs', value: METRIC_RAW },
    ])

    await waitFor(() => {
      expect(screen.getByTestId('system')).toHaveTextContent('metric')
    })
  })

  it('an anonymous visitor who chose imperial keeps it on a metric-default instance', async () => {
    // The other half, and the one that makes the fix safe: a default is what
    // you get before you choose, not something that overrides a choice.
    localStorage.setItem('unit_preference', 'imperial')
    reloadBrowserPrefs()

    mountWithPublicSettings([
      { key: 'auth_mode', value: 'none' },
      { key: 'default_unit_prefs', value: METRIC_RAW },
    ])

    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('false')
    })
    expect(screen.getByTestId('system')).toHaveTextContent('imperial')
    // The default was still parsed and retained; it simply lost.
    expect(screen.getByTestId('defaults-volume')).toHaveTextContent('L')
  })

  it('an anonymous visitor who chose metric keeps it on an auth_mode=none UK instance', async () => {
    // ★ The regression this ordering exists to prevent. Such an instance has no
    // other units control, and 093 can only ever seed imperial or UK-imperial,
    // so a default that outranked this key would make metric unreachable.
    localStorage.setItem('unit_preference', 'metric')
    reloadBrowserPrefs()

    mountWithPublicSettings([
      { key: 'auth_mode', value: 'none' },
      { key: 'default_unit_prefs', value: UK_IMPERIAL_RAW },
    ])

    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('false')
    })
    expect(screen.getByTestId('system')).toHaveTextContent('metric')
  })

  it('an anonymous visitor who never chose gets the UK-imperial instance default', async () => {
    // 'imperial' alone would be vacuous here, since it is also the terminal
    // fallback. The gallon standard is what discriminates: the cache is pinned
    // to 'us', so 'uk' can only have come from the published default.
    mountWithPublicSettings([
      { key: 'auth_mode', value: 'none' },
      { key: 'default_unit_prefs', value: UK_IMPERIAL_RAW },
    ])

    await waitFor(() => {
      expect(screen.getByTestId('gallon-standard')).toHaveTextContent('uk')
    })
    expect(screen.getByTestId('system')).toHaveTextContent('imperial')
    expect(screen.getByTestId('defaults-volume')).toHaveTextContent('gal_uk')
    expect(screen.getByTestId('defaults-secondary-gallon')).toHaveTextContent('uk')
  })

  it('an authenticated account outranks the instance default', async () => {
    localStorage.setItem('unit_preference', 'metric')
    reloadBrowserPrefs()
    mockedApi.get.mockImplementation((url: string) => {
      if (url === '/settings/public') {
        return Promise.resolve({
          data: {
            settings: [
              { key: 'auth_mode', value: 'local' },
              { key: 'default_unit_prefs', value: METRIC_RAW },
            ],
          },
        })
      }
      if (url === '/auth/me') {
        return Promise.resolve({ data: makeUser({ unit_preference: 'imperial' }) })
      }
      return Promise.reject(new Error('unexpected url'))
    })

    render(
      <AuthProvider>
        <Consumer />
      </AuthProvider>
    )

    await waitFor(() => {
      expect(screen.getByTestId('system')).toHaveTextContent('imperial')
    })
    // The instance default is still retained; it just lost.
    expect(screen.getByTestId('defaults-volume')).toHaveTextContent('L')
  })

  it('retains no default when the published row is malformed', async () => {
    localStorage.setItem('unit_preference', 'metric')
    reloadBrowserPrefs()

    mountWithPublicSettings([
      { key: 'auth_mode', value: 'none' },
      { key: 'default_unit_prefs', value: '{not json' },
    ])

    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('false')
    })
    expect(screen.getByTestId('defaults-present')).toHaveTextContent('false')
    expect(screen.getByTestId('system')).toHaveTextContent('metric')
  })

  it('retains no default when the instance publishes none', async () => {
    localStorage.setItem('unit_preference', 'metric')
    reloadBrowserPrefs()

    mountWithPublicSettings([{ key: 'auth_mode', value: 'none' }])

    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('false')
    })
    expect(screen.getByTestId('defaults-present')).toHaveTextContent('false')
    expect(screen.getByTestId('system')).toHaveTextContent('metric')
  })

  it('a failed settings fetch still finishes loading and leaves the browser in charge', async () => {
    // Round 1 shipped this test asserting `defaults-present` false and `system`
    // imperial with an empty localStorage, which holds whether or not any code
    // in the diff runs: `defaultUnitPrefs` initialises to null and imperial is
    // the terminal fallback. It was vacuous and survived every mutation.
    //
    // Two halves that a mutation CAN break: `loading` reaching false depends on
    // `setLoading(false)` staying in loadUser's `finally` rather than moving
    // into the try, which a fetch that throws would then skip forever; and
    // `system` reading metric depends on the browser's own choice still being
    // consulted when the server answered with nothing at all.
    localStorage.setItem('unit_preference', 'metric')
    reloadBrowserPrefs()
    mockedApi.get.mockImplementation(() => Promise.reject(new Error('offline')))

    render(
      <AuthProvider>
        <Consumer />
      </AuthProvider>
    )

    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('false')
    })
    expect(screen.getByTestId('defaults-present')).toHaveTextContent('false')
    expect(screen.getByTestId('system')).toHaveTextContent('metric')
  })
})
