/**
 * The Units card: the only place unit preferences are written.
 *
 * Two regressions live on `main` and both are repaired here.
 *
 * 1. `SettingsSystemTab` sent `api.put('/auth/me', { unit_preference })`.
 *    D9b removed that field from `UserSelfUpdate`, so the call is now a 422:
 *    every user who touched the units buttons got an error toast and a revert.
 *    The frontend suite could not see it, because `@/services/api` is mocked and
 *    a mock accepts any body. The card writes `PUT /auth/me/units` instead.
 * 2. For a client with no account the tab wrote the legacy `unit_preference`
 *    and `show_both_units` localStorage keys directly. `unitPrefsStore` ignores
 *    those once its own key exists, so the anonymous toggle changed nothing at
 *    all. The card calls `setUnitPrefs`.
 *
 * ★ WHY THE HIGHLIGHT COMES FROM THE STORED TAG AND NOT FROM THE RESOLVED SET.
 * An account can hold `unit_preference='metric'` with UK-imperial override
 * columns: `PUT /auth/me` used to write the preference and never cleared an
 * override, and migration 093 materialised all eleven for UK instances. The
 * card highlights the preset the account has RECORDED and states the units it
 * RESOLVES to right underneath, so that disagreement is visible and the
 * highlighted button is the lever that repairs it. Highlighting the derived tag
 * instead would hide the contradiction behind a third state and leave the user
 * pressing a button that is already "correct".
 *
 * ★ WHICH MAKES THE SAME-VALUE EARLY RETURN THE MOST EXPENSIVE MISTAKE
 * AVAILABLE HERE. `if (next === current) return` in the click handler leaves
 * every override column in place for exactly the population this phase exists
 * to fix, while every other test in this file still passes. Two cases below
 * pin it, because there are two ways to write it: comparing the TAG, and
 * comparing the RESOLVED SET.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {
  IMPERIAL_UNITS,
  METRIC_UNITS,
  UK_IMPERIAL_UNITS,
  makeUser,
  type User,
} from '@/__tests__/factories'
import {
  UNIT_FIELD_NAMES,
  UNIT_OPTIONS,
  UNIT_OPTION_LABELS,
  unitOptionsFor,
  type UnitSet,
} from '@/types/units'

const h = vi.hoisted(() => ({
  user: null as User | null,
  isAuthenticated: true,
  defaultUnitPrefs: null as UnitSet | null,
  refreshUser: vi.fn(),
}))

vi.mock('@/services/api', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
  },
}))

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({
    isAuthenticated: h.isAuthenticated,
    isAdmin: true,
    user: h.user,
    defaultUnitPrefs: h.defaultUnitPrefs,
    refreshUser: h.refreshUser,
  }),
}))

// Every label in this card is a translation key, and D10's whole claim is about
// what those keys RESOLVE to: a select offering the raw token `kpa` would pass
// a key-echoing mock. So `t` goes through the app's own i18next instance, with
// the same stable-reference pinning the sibling settings tests use (a fresh `t`
// per call re-fires load effects forever).
vi.mock('react-i18next', () => {
  const t = (key: string, opts?: Record<string, unknown>): string =>
    i18n.t(key.includes(':') ? key : `settings:${key}`, opts ?? {})
  return {
    useTranslation: () => ({
      t,
      i18n: { language: 'en', changeLanguage: () => Promise.resolve() },
    }),
    Trans: ({ children }: { children: React.ReactNode }) => children,
    initReactI18next: { type: '3rdParty', init: () => {} },
  }
})

import i18n from '@/i18n'
import api from '@/services/api'
import { getUnitPrefs, setUnitPrefs } from '@/utils/unitPrefsStore'
import UnitPreferencesCard from '../UnitPreferencesCard'

const mockedApi = vi.mocked(api)

/** Resolve a key the way the card does, so the queries below cannot drift. */
function label(key: string): string {
  return i18n.t(key.includes(':') ? key : `settings:${key}`)
}

/**
 * Let the browser preference store re-read `localStorage`.
 *
 * The store parses once at module load and holds the object, so a `clear()` in
 * a test body is invisible to it until a `storage` event arrives. This is the
 * same arrangement `useUnitPreference.precedence.test.tsx` uses.
 */
function reloadBrowserPrefs(): void {
  window.dispatchEvent(new Event('storage'))
}

/** Mount the card for the currently arranged auth state. */
function renderCard(): void {
  render(<UnitPreferencesCard />)
}

/** Mount as an authenticated account. */
function renderAs(user: User): void {
  h.isAuthenticated = true
  h.user = user
  renderCard()
}

/** Mount as a client with no account, on an instance publishing `defaults`. */
function renderAnonymous(defaults: UnitSet): void {
  h.isAuthenticated = false
  h.user = null
  h.defaultUnitPrefs = defaults
  renderCard()
}

/** The tri-state button for one choice. */
function presetButton(key: 'units.imperial' | 'units.metric' | 'units.custom'): HTMLElement {
  return screen.getByRole('button', { name: label(key) })
}

/** Click a preset and accept the confirmation it must show first. */
async function choosePreset(key: 'units.imperial' | 'units.metric'): Promise<void> {
  await userEvent.click(presetButton(key))
  await userEvent.click(screen.getByRole('button', { name: label('units.presetConfirmAction') }))
}

describe('UnitPreferencesCard: the account writer', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    reloadBrowserPrefs()
    h.isAuthenticated = true
    h.user = null
    h.defaultUnitPrefs = null
    h.refreshUser = vi.fn()
    mockedApi.put.mockResolvedValue({ data: {} })
    mockedApi.post.mockResolvedValue({ data: {} })
    mockedApi.get.mockResolvedValue({ data: {} })
  })

  it('shows no per-quantity control until Custom is chosen', async () => {
    renderAs(makeUser({ unit_preference: 'metric', resolved_units: METRIC_UNITS }))

    // Both directions. The absence is satisfied by an empty card and proves
    // nothing on its own; the appearance is the half that is false at t=0.
    expect(screen.queryByLabelText(label(UNIT_OPTION_LABELS.pressure.labelKey))).toBeNull()

    await userEvent.click(presetButton('units.custom'))

    expect(screen.getByLabelText(label(UNIT_OPTION_LABELS.pressure.labelKey))).toBeInstanceOf(
      HTMLSelectElement,
    )
  })

  it('shows all eleven quantities under Custom, secondary_gallon included, with show-both off', async () => {
    // R7 / D4b: `secondary_gallon` is not gated on show-both. A metric Custom
    // account with the toggle OFF still needs it, because the widget endpoints
    // always emit MPG and something has to say which gallon that MPG means.
    renderAs(
      makeUser({
        unit_preference: 'custom',
        resolved_units: METRIC_UNITS,
        show_both_units: false,
      }),
    )

    expect(screen.getByRole('checkbox', { name: label('units.showBoth') })).not.toBeChecked()

    // Enumerated from the type, in both directions: no quantity missing and
    // none invented. A hand-written list of eleven names is a floor.
    const rendered = UNIT_FIELD_NAMES.filter(
      (field) => screen.queryByLabelText(label(UNIT_OPTION_LABELS[field].labelKey)) !== null,
    )
    expect(rendered).toStrictEqual(UNIT_FIELD_NAMES)
    expect(rendered).toContain('secondary_gallon')
  })

  it('★ clicking the already-highlighted preset still clears the overrides', async () => {
    // The reachable state: `PUT /auth/me` wrote `unit_preference` and never
    // cleared an override (backend/app/routes/auth.py:321), and migration 093
    // materialised all eleven for UK instances. So this account is TAGGED
    // metric and RESOLVES to UK imperial, and Metric is the highlighted button.
    renderAs(makeUser({ unit_preference: 'metric', resolved_units: UK_IMPERIAL_UNITS }))

    // Precondition, asserted rather than assumed: without this the test is not
    // the same-value case it claims to be.
    expect(presetButton('units.metric')).toHaveAttribute('aria-pressed', 'true')

    await choosePreset('units.metric')

    await waitFor(() =>
      expect(mockedApi.put).toHaveBeenCalledWith('/auth/me/units', { unit_preference: 'metric' }),
    )
  })

  it('★ clicking the highlighted preset writes even when the set already matches it', async () => {
    // The other half of the same trap. The case above is defeated by comparing
    // TAGS; this one is defeated by comparing RESOLVED SETS, and an
    // implementation can carry either early return alone.
    renderAs(makeUser({ unit_preference: 'metric', resolved_units: METRIC_UNITS }))

    expect(presetButton('units.metric')).toHaveAttribute('aria-pressed', 'true')

    await choosePreset('units.metric')

    await waitFor(() =>
      expect(mockedApi.put).toHaveBeenCalledWith('/auth/me/units', { unit_preference: 'metric' }),
    )
  })

  it('sends one request that clears the overrides when a preset is chosen', async () => {
    renderAs(makeUser({ unit_preference: 'custom', resolved_units: METRIC_UNITS }))

    await choosePreset('units.imperial')

    // Exactly this body. One carrying the current units would re-materialise
    // what it just cleared, and a second request would mean the show-both
    // write is still riding a separate endpoint.
    await waitFor(() =>
      expect(mockedApi.put).toHaveBeenCalledWith('/auth/me/units', { unit_preference: 'imperial' }),
    )
    expect(mockedApi.put).toHaveBeenCalledTimes(1)
  })

  it('warns a UK account that choosing Imperial moves it to US gallons, before writing', async () => {
    renderAs(makeUser({ unit_preference: 'custom', resolved_units: UK_IMPERIAL_UNITS }))

    await userEvent.click(presetButton('units.imperial'))

    expect(screen.getByText(label('units.presetConfirmGallon'))).toBeInTheDocument()
    expect(mockedApi.put).not.toHaveBeenCalled()

    await userEvent.click(screen.getByRole('button', { name: label('units.presetConfirmAction') }))
    await waitFor(() => expect(mockedApi.put).toHaveBeenCalled())
  })

  it('does not warn about gallons when the account is already on US gallons', async () => {
    // The mirror: without it the warning could be unconditional and the case
    // above would still pass.
    renderAs(makeUser({ unit_preference: 'custom', resolved_units: METRIC_UNITS }))

    await userEvent.click(presetButton('units.imperial'))

    expect(screen.getByText(label('units.presetConfirmMessage'))).toBeInTheDocument()
    expect(screen.queryByText(label('units.presetConfirmGallon'))).toBeNull()
  })

  it('★ seeds Custom from the resolved set, not from the preset base', async () => {
    // ★ THE BACKEND DOES NOT ENFORCE THIS HALF. `UnitPreferenceUpdate` validates
    // only that a full valid set arrived; it accepts any eleven. D3 says
    // Custom materialises "all eleven FROM THE CURRENTLY RESOLVED SET", and this
    // is the only thing holding that half of the rule anywhere in the system.
    //
    // The starting state is a PRESET marker whose resolved set differs from its
    // preset. Starting from an already-custom account would prove nothing:
    // `presetUnitsFor('custom')` does not typecheck, so the wrong
    // implementation is unreachable from there.
    renderAs(makeUser({ unit_preference: 'metric', resolved_units: UK_IMPERIAL_UNITS }))

    await userEvent.click(presetButton('units.custom'))

    await waitFor(() =>
      expect(mockedApi.put).toHaveBeenCalledWith('/auth/me/units', {
        unit_preference: 'custom',
        units: UK_IMPERIAL_UNITS,
      }),
    )

    // And the eleven controls show that same set, so what was submitted and
    // what is on screen cannot disagree.
    const shown = Object.fromEntries(
      UNIT_FIELD_NAMES.map((field) => [
        field,
        (screen.getByLabelText(label(UNIT_OPTION_LABELS[field].labelKey)) as HTMLSelectElement)
          .value,
      ]),
    )
    expect(shown).toStrictEqual(UK_IMPERIAL_UNITS)
  })

  it('submits the whole set with one quantity changed when a control moves', async () => {
    renderAs(makeUser({ unit_preference: 'custom', resolved_units: METRIC_UNITS }))

    await userEvent.selectOptions(
      screen.getByLabelText(label(UNIT_OPTION_LABELS.pressure.labelKey)),
      'psi',
    )

    await waitFor(() =>
      expect(mockedApi.put).toHaveBeenCalledWith('/auth/me/units', {
        unit_preference: 'custom',
        units: { ...METRIC_UNITS, pressure: 'psi' },
      }),
    )
  })

  it('refreshes the user after an authenticated save', async () => {
    // ★ `useUnitPreference` reads `user` from AuthContext, which changes only
    // when `refreshUser` reloads it (AuthContext.tsx:166-168). Without this the
    // card saves and the screen does not move. TRUE the moment the card works,
    // so its proof is a deliberate mutation, recorded in the report.
    renderAs(makeUser({ unit_preference: 'custom', resolved_units: METRIC_UNITS }))

    await choosePreset('units.metric')

    await waitFor(() => expect(h.refreshUser).toHaveBeenCalled())
  })

  it('★ sends show-both in the SAME request as the preference', async () => {
    // R2. Today's tab writes show-both to `/auth/me` on its own; without this
    // an implementer can keep that second call and nothing notices.
    renderAs(
      makeUser({
        unit_preference: 'metric',
        resolved_units: METRIC_UNITS,
        show_both_units: false,
      }),
    )

    await userEvent.click(screen.getByRole('checkbox', { name: label('units.showBoth') }))

    await waitFor(() =>
      expect(mockedApi.put).toHaveBeenCalledWith('/auth/me/units', {
        unit_preference: 'metric',
        show_both_units: true,
      }),
    )
    expect(mockedApi.put).toHaveBeenCalledTimes(1)
  })

  it('★ toggling show-both does not let a stale preset tag clear the overrides', async () => {
    // The same reachable state as the same-value case: tagged metric, resolving
    // to UK imperial. `PUT /auth/me/units` writes eleven nulls for ANY preset,
    // so echoing the stored tag here would wipe this account's units as a side
    // effect of a display toggle. The honest request materialises what the
    // account already resolves to, which changes nothing it renders.
    renderAs(
      makeUser({
        unit_preference: 'metric',
        resolved_units: UK_IMPERIAL_UNITS,
        show_both_units: false,
      }),
    )

    await userEvent.click(screen.getByRole('checkbox', { name: label('units.showBoth') }))

    await waitFor(() =>
      expect(mockedApi.put).toHaveBeenCalledWith('/auth/me/units', {
        unit_preference: 'custom',
        units: UK_IMPERIAL_UNITS,
        show_both_units: true,
      }),
    )
  })

  it('never writes a unit field through the generic profile route', async () => {
    // The regression, stated as an invariant rather than as one call site:
    // `UserSelfUpdate` has carried no `unit_preference` since D9b, so any
    // `/auth/me` write from this card is a 422 in production and silent here.
    renderAs(makeUser({ unit_preference: 'custom', resolved_units: METRIC_UNITS }))

    await choosePreset('units.imperial')
    await waitFor(() => expect(mockedApi.put).toHaveBeenCalled())

    const routes = mockedApi.put.mock.calls.map(([url]) => url)
    expect(routes).toStrictEqual(['/auth/me/units'])
  })
})

describe('UnitPreferencesCard: the client with no account', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    reloadBrowserPrefs()
    h.isAuthenticated = false
    h.user = null
    h.defaultUnitPrefs = null
    h.refreshUser = vi.fn()
    mockedApi.put.mockResolvedValue({ data: {} })
    mockedApi.post.mockResolvedValue({ data: {} })
    mockedApi.get.mockResolvedValue({ data: {} })
  })

  it('writes to the store, not the API, for a client with no account', async () => {
    renderAnonymous(IMPERIAL_UNITS)

    await choosePreset('units.metric')

    await waitFor(() => expect(getUnitPrefs()?.units?.distance).toBe('km'))
    expect(getUnitPrefs()?.units).toStrictEqual(METRIC_UNITS)
    expect(mockedApi.put).not.toHaveBeenCalled()
  })

  it('lands a client with no account on US gallons when it chooses Imperial', async () => {
    // R4, the anonymous half. `base_preset_for('imperial')` on the backend is
    // the US preset, so the two writers must agree or the same button means two
    // things depending on whether you have an account.
    setUnitPrefs({ units: UK_IMPERIAL_UNITS, unit_preference: null, show_both_units: false })
    renderAnonymous(METRIC_UNITS)

    await choosePreset('units.imperial')

    await waitFor(() => expect(getUnitPrefs()?.units).toStrictEqual(IMPERIAL_UNITS))
  })

  it('toggles show-both for a client with no account', async () => {
    setUnitPrefs({ units: METRIC_UNITS, unit_preference: null, show_both_units: false })
    renderAnonymous(METRIC_UNITS)

    await userEvent.click(screen.getByRole('checkbox', { name: label('units.showBoth') }))

    await waitFor(() => expect(getUnitPrefs()?.show_both_units).toBe(true))
    // And it must not disturb the set it rides beside.
    expect(getUnitPrefs()?.units).toStrictEqual(METRIC_UNITS)
    expect(mockedApi.put).not.toHaveBeenCalled()
  })

  it('★ does not pin an unchosen client to the instance default when it only toggles show-both', async () => {
    // The store carries a NULLABLE `units` precisely so a modifier can be held
    // without activating rung 2. Writing the resolved set here would invent an
    // explicit browser choice that outranks `default_unit_prefs` forever, so a
    // metric instance changing its default would stop reaching this browser.
    renderAnonymous(METRIC_UNITS)

    await userEvent.click(screen.getByRole('checkbox', { name: label('units.showBoth') }))

    await waitFor(() => expect(getUnitPrefs()?.show_both_units).toBe(true))
    expect(getUnitPrefs()?.units).toBeNull()
  })

  it('★ labels a MIGRATED record by the set it renders, not by the tag the store derived', async () => {
    // ★ THE CARD HAS TO FOLLOW RUNG 2 OFF THE LEGACY KEYS. The store derives a
    // tag from the set `migrateLegacy` built, which is imperial + the dead
    // `imperial_gallon_standard` cache; `useUnitPreference` then keeps only the
    // binary system and takes the flavour from the instance, so this client
    // RENDERS UK gallons. Reading the stored tag anyway highlights "Imperial"
    // over a set that says gal_uk and hides the Custom grid, which is the exact
    // dishonesty migration 093 fixed server-side and the reason `presetTagFor`
    // lives beside the presets rather than in each caller.
    localStorage.setItem('unit_preference', 'imperial')
    localStorage.setItem('imperial_gallon_standard', 'us')
    reloadBrowserPrefs()
    renderAnonymous(UK_IMPERIAL_UNITS)

    expect(presetButton('units.custom')).toHaveAttribute('aria-pressed', 'true')
    expect(presetButton('units.imperial')).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getByLabelText(label(UNIT_OPTION_LABELS.volume.labelKey))).toHaveValue('gal_uk')
  })

  it('★ still labels a CHOSEN record by its own stored tag', async () => {
    // The mirror, so the guard above cannot be over-applied into "never trust
    // the store's tag". This client chose the metric preset through the card;
    // the instance publishes imperial and must not relabel it.
    setUnitPrefs({ units: METRIC_UNITS, unit_preference: 'metric', show_both_units: false })
    renderAnonymous(IMPERIAL_UNITS)

    expect(presetButton('units.metric')).toHaveAttribute('aria-pressed', 'true')
    expect(presetButton('units.custom')).toHaveAttribute('aria-pressed', 'false')
  })

  it('writes a full custom set to the store when a quantity changes', async () => {
    setUnitPrefs({ units: METRIC_UNITS, unit_preference: null, show_both_units: false })
    renderAnonymous(METRIC_UNITS)

    await userEvent.click(presetButton('units.custom'))
    await userEvent.selectOptions(
      screen.getByLabelText(label(UNIT_OPTION_LABELS.pressure.labelKey)),
      'psi',
    )

    await waitFor(() =>
      expect(getUnitPrefs()?.units).toStrictEqual({ ...METRIC_UNITS, pressure: 'psi' }),
    )
    expect(mockedApi.put).not.toHaveBeenCalled()
  })
})

describe('UnitPreferencesCard, D10: unit names are translated, symbols are not', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    reloadBrowserPrefs()
    h.isAuthenticated = true
    h.user = null
    h.defaultUnitPrefs = null
    mockedApi.put.mockResolvedValue({ data: {} })
    mockedApi.post.mockResolvedValue({ data: {} })
    mockedApi.get.mockResolvedValue({ data: {} })
  })

  it('★ resolves an English name for every option of every quantity', async () => {
    // Enumerated from `UNIT_OPTIONS`, never hand-listed: three spot checks
    // would leave a silently raw token in the twenty-third select.
    //
    // ★ `i18n.exists`, not `t(key) === key`. A missing `settings:units.foo`
    // resolves to `units.foo`, the key MINUS its namespace, so the obvious
    // comparison is false for every missing key and the guard passes against a
    // locale file with none of these strings in it. That is exactly what the
    // first draft of this test did, and the red run caught it: 19 failures and
    // these 2 green.
    const raw: string[] = []
    const untranslated: string[] = []
    for (const field of UNIT_FIELD_NAMES) {
      for (const option of unitOptionsFor(field)) {
        const text = i18n.t(option.labelKey)
        if (!i18n.exists(option.labelKey) || text === '') untranslated.push(option.labelKey)
        if (text === option.value) raw.push(option.labelKey)
      }
    }
    expect(untranslated).toStrictEqual([])
    expect(raw).toStrictEqual([])

    // And the count, so a table that lost a whole quantity's options cannot
    // pass by having nothing left to check.
    const total = UNIT_FIELD_NAMES.reduce((n, field) => n + UNIT_OPTIONS[field].length, 0)
    expect(total).toBe(26)
  })

  it('resolves an English name for every quantity heading', () => {
    // `exists`, for the reason the option test states.
    const untranslated = UNIT_FIELD_NAMES.filter(
      (field) => !i18n.exists(UNIT_OPTION_LABELS[field].labelKey),
    )
    expect(untranslated).toStrictEqual([])
  })

  it('★ renders the names, not the tokens, in a per-quantity control', async () => {
    // The coverage test above proves the keys resolve; this proves the card
    // actually asks for them. An implementation dropping `UNIT_OPTIONS` straight
    // into `Select` passes every other test in this file and renders `kpa`.
    renderAs(makeUser({ unit_preference: 'custom', resolved_units: METRIC_UNITS }))

    const pressure = screen.getByLabelText(label(UNIT_OPTION_LABELS.pressure.labelKey))
    const texts = within(pressure)
      .getAllByRole('option')
      .map((option) => option.textContent)
    expect(texts).toStrictEqual([
      'Kilopascals (kPa)',
      'Bar (bar)',
      'Pounds per square inch (PSI)',
    ])
  })
})
