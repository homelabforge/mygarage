/**
 * The Units card describes the set the account RESOLVES to, per quantity.
 *
 * Three defects, all in the same line of the same file:
 *
 * 1. Migration 093 materialises a UK instance's imperial users as
 *    `unit_preference='custom'`. Branching the gallon sub-panel on
 *    `unitPreference === 'imperial'` removed their only UI for changing gallon
 *    flavour.
 *
 * 2. The description used to be one of two fixed sentences chosen by the
 *    collapsed binary system, which is derived from VOLUME (spec D8). A
 *    `{volume:'L', distance:'mi', pressure:'psi'}` account was therefore told
 *    "Using metric units: liters, kilometers, L/100km, °C, bar, kg, Nm" while
 *    it renders miles and PSI. Plan 3b ruling R1 calls that a false statement
 *    rather than copy needing an exemption, so the sentence is COMPOSED from
 *    the resolved set.
 *
 * 3. ★ The first fix for (2) composed from `presetUnitsFor(unitPreference, ...)`
 *    whenever the preference was `imperial` or `metric`, which contradicts
 *    spec D3: an override column beats the preset for every account, not only
 *    for `custom` ones. `PUT /auth/me` writes `unit_preference` and never
 *    clears an override, so `{preference: 'metric', overrides: UK imperial}` is
 *    a state the product creates on purpose, and it painted metric units and
 *    hid the gallon panel. The `D3` block below is that case, both directions.
 *
 * ★ THE DESCRIPTION KEY IS RESOLVED THROUGH THE APP'S OWN i18next INSTANCE,
 * not through a hand-rolled substitution. The composed list contains `/` in
 * three of its labels (`L/100km`, `km/L`, `/32 in`), and i18next escapes
 * interpolated values by default; only `src/i18n.ts`'s `escapeValue: false`
 * makes them render as themselves. A test that spelled its own `.replace()`
 * would assert a sentence no user can get. Every other key echoes, matching the
 * global mock.
 *
 * ★ THE GALLON PANEL HALF OF EVERY CASE IS GONE, and it did not lapse quietly.
 * Each case used to assert the sentence and the panel's visibility together in
 * one `toStrictEqual`, because the card derived both from ONE expression and a
 * case reading only one of them left that claim undefended. Phase 4 task 5
 * deleted the panel with the `imperial_gallon_standard` control it wrote:
 * `components/settings/InstanceUnitDefaultsCard.tsx` writes the whole
 * `default_unit_prefs` set instead, through the same eleven controls, so there
 * is no second expression left to agree with. What survives is the sentence,
 * read through `readCard` so a case still cannot pass on a `findByText` that
 * already threw.
 *
 * ★ AND THE TWO CASE NAMES THAT STILL SAID "gallon panel" ARE RENAMED. Their
 * bodies stopped asserting anything about a panel when it was deleted, so the
 * names claimed a property the bodies no longer exercised, which is this
 * project's own named anti-pattern and worse than a missing test: a reader
 * greps for the guard, finds it, and stops looking. They assert the composed
 * sentence for a `custom` account, which is what they now check and all they
 * now check.
 *
 * ★ THE CARD LIVES IN QUICK SETTINGS NOW, so it is mounted here on its own,
 * in the drawer's `compact` layout. Settings > System keeps only
 * `InstanceUnitDefaultsCard`, the instance default; the two editors' controls
 * are deliberately identical, which is why every query below stays scoped to
 * the account card's region (the drawer can be open over the settings page).
 * The card's write paths are covered in `UnitPreferencesCard.test.tsx`.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  IMPERIAL_UNITS,
  METRIC_UNITS,
  UK_IMPERIAL_UNITS,
  makeUser,
  type User,
} from '@/__tests__/factories'
import type { UnitSet } from '@/types/units'

/** The composed description, as the component asks for it. */
const DESCRIPTION_KEY = 'units.resolvedDescription'

/**
 * The show-both toggle's description, which task 6b also made composed.
 *
 * It used to read 'Display values in both imperial and metric (e.g., "25 MPG
 * (9.4 L/100km)")'. Both halves were wrong for a resolved set: the counterpart
 * is chosen per QUANTITY rather than per system, and the example was fixed in
 * one direction, so a metric reader was shown the reverse of what the toggle
 * would actually do to their screen. The example is now rendered through their
 * own consumption formatter with show-both ON, which is the toggle's effect
 * demonstrated rather than described.
 */
const SHOW_BOTH_KEY = 'units.showBothDescription'

/** Hand-written from `UNIT_ADAPTERS`, in `UNIT_QUANTITIES` order. */
const IMPERIAL_TEXT = 'Using these units: mi, mph, ft, gal, MPG, PSI, °F, lb, lb-ft, /32 in'
const METRIC_TEXT = 'Using these units: km, km/h, m, L, L/100km, kPa, °C, kg, Nm, mm'

const h = vi.hoisted(() => ({
  user: null as User | null,
  resolve: null as ((key: string, opts?: Record<string, unknown>) => string) | null,
}))

vi.mock('@/services/api', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
  },
}))

// See SettingsSystemTab.test.tsx: the global setup mock returns a fresh `t`
// per call, which re-fires load effects forever. Pin a stable reference.
vi.mock('react-i18next', () => {
  const t = (key: string, opts?: Record<string, unknown>): string => h.resolve?.(key, opts) ?? key
  return {
    useTranslation: () => ({
      t,
      i18n: { language: 'en', changeLanguage: () => Promise.resolve() },
    }),
    Trans: ({ children }: { children: React.ReactNode }) => children,
    initReactI18next: { type: '3rdParty', init: () => {} },
  }
})

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({
    isAuthenticated: true,
    isAdmin: true,
    user: h.user,
    refreshUser: vi.fn(),
    refreshPublicSettings: vi.fn(),
    householdTimeZone: null,
  }),
}))

import i18n from '@/i18n'
import api from '@/services/api'
import UnitPreferencesCard from '../UnitPreferencesCard'

h.resolve = (key, opts) =>
  key === DESCRIPTION_KEY || key === SHOW_BOTH_KEY
    ? i18n.t(`settings:${key}`, opts ?? {})
    : key

const mockedApi = vi.mocked(api)

/** Mount the card as Quick Settings does. */
function renderCard(): void {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={queryClient}>
      <UnitPreferencesCard />
    </QueryClientProvider>,
  )
}

/** What the Units card says about the units this client renders. */
interface UnitsCard {
  description: string
}

/** The account card's own region, never the instance-default card's. */
function accountCard(): HTMLElement {
  return screen.getByRole('region', { name: 'units.label' })
}

/** Read the card back once it has settled. */
async function readCard(): Promise<UnitsCard> {
  const paragraph = await screen.findByText(/^Using these units: /)
  return { description: paragraph.textContent ?? '' }
}

/** Mount as `user` and read the Units card back. */
async function cardFor(user: User): Promise<UnitsCard> {
  h.user = user
  renderCard()
  return readCard()
}

describe('UnitPreferencesCard — the Units card reads the resolved set', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    h.user = null
    mockedApi.get.mockImplementation((url: string) => {
      if (url === '/settings') {
        return Promise.resolve({
          data: { settings: [{ key: 'timezone', value: 'UTC' }] },
        })
      }
      if (url === '/auth/users/count') return Promise.resolve({ data: { has_users: true } })
      if (url === '/dashboard') return Promise.resolve({ data: { total_vehicles: 0 } })
      if (url === '/health') return Promise.resolve({ data: { authenticator_detected: false } })
      return Promise.resolve({ data: {} })
    })
    mockedApi.post.mockResolvedValue({ data: { settings: [], total: 0 } })
    mockedApi.put.mockResolvedValue({ data: {} })
  })

  it('describes a custom account resolving to UK gallons in gallons, not litres', async () => {
    const card = await cardFor(
      makeUser({ unit_preference: 'custom', resolved_units: UK_IMPERIAL_UNITS }),
    )
    expect(card).toStrictEqual({ description: IMPERIAL_TEXT })
  })

  it('describes a custom account resolving to litres in litres, not gallons', async () => {
    const card = await cardFor(
      makeUser({ unit_preference: 'custom', resolved_units: METRIC_UNITS }),
    )
    expect(card).toStrictEqual({ description: METRIC_TEXT })
  })

  it('describes a preset imperial account in the units it renders', async () => {
    const card = await cardFor(
      makeUser({ unit_preference: 'imperial', resolved_units: IMPERIAL_UNITS }),
    )
    expect(card).toStrictEqual({ description: IMPERIAL_TEXT })
  })

  it('describes a preset metric account with kPa, which the retired copy called bar', async () => {
    const card = await cardFor(
      makeUser({ unit_preference: 'metric', resolved_units: METRIC_UNITS }),
    )
    expect(card).toStrictEqual({ description: METRIC_TEXT })
  })

  it('names miles and PSI for the litres-and-miles account R1 describes', async () => {
    // The exact set from plan 3b R1. `binarySystemFor('L')` is metric, so the
    // retired copy told this reader "kilometers ... bar".
    const units: UnitSet = { ...METRIC_UNITS, distance: 'mi', pressure: 'psi' }
    const card = await cardFor(makeUser({ unit_preference: 'custom', resolved_units: units }))
    expect(card).toStrictEqual({ description: 'Using these units: mi, km/h, m, L, L/100km, PSI, °C, kg, Nm, mm' })
  })

  it('names Celsius, Nm and mm for an otherwise imperial account', async () => {
    const units: UnitSet = { ...IMPERIAL_UNITS, temperature: 'c', torque: 'nm', tread: 'mm' }
    const card = await cardFor(makeUser({ unit_preference: 'custom', resolved_units: units }))
    expect(card).toStrictEqual({ description: 'Using these units: mi, mph, ft, gal, MPG, PSI, °C, lb, Nm, mm' })
  })

  it('names km/L and bar, which neither retired sentence could say', async () => {
    // `km_l` and `bar` are in no preset, so no fixed sentence could ever name
    // them: the metric one said `L/100km` and `bar`, and the metric PRESET
    // resolves `kpa`. Both halves were wrong in opposite directions.
    const units: UnitSet = {
      ...METRIC_UNITS,
      speed: 'mph',
      consumption: 'km_l',
      pressure: 'bar',
      mass: 'lb',
    }
    const card = await cardFor(makeUser({ unit_preference: 'custom', resolved_units: units }))
    expect(card).toStrictEqual({ description: 'Using these units: km, mph, m, L, km/L, bar, °C, lb, Nm, mm' })
  })
})

describe('UnitPreferencesCard — D3: an override column beats the preset', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    h.user = null
    mockedApi.get.mockImplementation((url: string) => {
      if (url === '/settings') {
        return Promise.resolve({
          data: { settings: [{ key: 'timezone', value: 'UTC' }] },
        })
      }
      if (url === '/auth/users/count') return Promise.resolve({ data: { has_users: true } })
      if (url === '/dashboard') return Promise.resolve({ data: { total_vehicles: 0 } })
      if (url === '/health') return Promise.resolve({ data: { authenticator_detected: false } })
      return Promise.resolve({ data: {} })
    })
    mockedApi.post.mockResolvedValue({ data: { settings: [], total: 0 } })
    mockedApi.put.mockResolvedValue({ data: {} })
  })

  it('renders gallons for a METRIC-preset account whose overrides are UK imperial', async () => {
    // Reachable on purpose: migration 093 materialises all eleven columns, and
    // `PUT /auth/me` sets the preference without clearing one. Composing from
    // the preference painted metric units and hid the gallon panel here.
    const card = await cardFor(
      makeUser({ unit_preference: 'metric', resolved_units: UK_IMPERIAL_UNITS }),
    )
    expect(card).toStrictEqual({ description: IMPERIAL_TEXT })
  })

  it('renders litres for an IMPERIAL-preset account whose overrides are metric', async () => {
    // The mirror. Without it, "use the preset" could be reintroduced for the
    // imperial half alone and one direction would still pass.
    const card = await cardFor(
      makeUser({ unit_preference: 'imperial', resolved_units: METRIC_UNITS }),
    )
    expect(card).toStrictEqual({ description: METRIC_TEXT })
  })

  it('does not repaint the card for a preset click the account still overrides', async () => {
    // The resting state of this account is pinned by the first case in the
    // block above, so it is not re-asserted here. What this adds is that the
    // CLICK lands and the card still reports the units the account actually
    // resolves to until `refreshUser` brings back a new set.
    //
    // ★ MIGRATED IN PHASE 4 TASK 4, AND THE OLD ASSERTION WAS A LIVE BUG
    // REPORT. It required `api.put('/auth/me', { unit_preference: 'metric' })`.
    // D9b had already removed `unit_preference` from `UserSelfUpdate`, so that
    // call is a 422 in production: the buttons showed an error toast and
    // reverted, for every user. This suite could not see it because
    // `@/services/api` is mocked and a mock accepts any body. Units now go to
    // the dedicated route, behind the confirmation D3 requires: choosing a
    // preset CLEARS every override column, and the UI has to say so first.
    h.user = makeUser({ unit_preference: 'custom', resolved_units: UK_IMPERIAL_UNITS })
    renderCard()
    await screen.findByText(/^Using these units: /)

    await userEvent.click(within(accountCard()).getByText('units.metric'))
    // The confirmation precedes the write. Asserted here, not assumed: without
    // it this test would pass against a card that writes on the first click.
    expect(mockedApi.put).not.toHaveBeenCalled()

    await userEvent.click(screen.getByText('units.presetConfirmAction'))
    await waitFor(() =>
      expect(mockedApi.put).toHaveBeenCalledWith('/auth/me/units', { unit_preference: 'metric' }),
    )

    expect(await readCard()).toStrictEqual({ description: IMPERIAL_TEXT })
  })
})

describe('UnitPreferencesCard — the show-both example demonstrates the reader\'s own pair', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    h.user = null
    mockedApi.get.mockImplementation((url: string) => {
      if (url === '/settings') {
        return Promise.resolve({ data: { settings: [{ key: 'timezone', value: 'UTC' }] } })
      }
      if (url === '/auth/users/count') return Promise.resolve({ data: { has_users: true } })
      if (url === '/dashboard') return Promise.resolve({ data: { total_vehicles: 0 } })
      if (url === '/health') return Promise.resolve({ data: { authenticator_detected: false } })
      return Promise.resolve({ data: {} })
    })
    mockedApi.post.mockResolvedValue({ data: { settings: [], total: 0 } })
  })

  /** Mount as `user` and read the show-both sentence back. */
  async function sentenceFor(user: User): Promise<string> {
    h.user = user
    renderCard()
    const paragraph = await screen.findByText(/^Show each value with its counterpart/)
    return paragraph.textContent ?? ''
  }

  it('★ shows an MPG-primary example to an MPG account', async () => {
    // The sample is 25 US MPG, converted to canonical 9.40856 L/100km.
    const sentence = await sentenceFor(
      makeUser({ unit_preference: 'custom', resolved_units: IMPERIAL_UNITS }),
    )
    expect(sentence).toBe(
      'Show each value with its counterpart in parentheses, for example 25.0 MPG (9.41 L/100km).',
    )
  })

  it('★ shows the REVERSE pair to a metric account, which the fixed example could not', async () => {
    const sentence = await sentenceFor(
      makeUser({ unit_preference: 'custom', resolved_units: METRIC_UNITS }),
    )
    expect(sentence).toBe(
      'Show each value with its counterpart in parentheses, for example 9.41 L/100km (25.0 MPG).',
    )
  })

  it('★ shows the UK gallon\'s MPG to a UK account, not the US one', async () => {
    // 282.4809363... / 9.40856 = 30.02, one decimal 30.0. The retired sentence said 25 MPG to everyone,
    // which is not even the right number for this reader.
    const sentence = await sentenceFor(
      makeUser({ unit_preference: 'custom', resolved_units: UK_IMPERIAL_UNITS }),
    )
    expect(sentence).toBe(
      'Show each value with its counterpart in parentheses, for example 30.0 MPG (9.41 L/100km).',
    )
  })
})
