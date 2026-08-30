/**
 * The instance-default units card: the admin's writer for `default_unit_prefs`.
 *
 * ★ WHY IT EXISTS AT ALL, because "delete two frontend modules" was the earlier
 * framing and it would have left a real gap. Until this card, the admin's only
 * way to move the instance-wide default for anonymous visitors and for every
 * client on an `auth_mode=none` instance was the standalone gallon control that
 * task 5 retires. Removing that with nothing in its place is D5's own failure
 * mode ("retiring it with nothing in its place strands them"), moved from users
 * to instances. Ruling R5: phase 4 adds this control and keeps the backend
 * `imperial_gallon_standard` row as a seed and fallback only.
 *
 * ★ THREE THINGS HERE ARE NOT STYLE POINTS.
 *
 * 1. THE BATCH ROUTE, NOT `PUT /settings/{key}`. Two materially different paths
 *    exist: the single-key PUT 404s when the row is absent, and the batch route
 *    upserts. Migration 093 seeds the row, but an instance whose row was deleted
 *    is exactly the case the backend fallback exists for, and the batch route is
 *    the one that can recover it.
 * 2. `isAdmin || authMode === 'none'`, NEVER `isAdmin` ALONE. In
 *    `auth_mode=none` the backend deliberately allows settings administration
 *    and returns no user, while the frontend reports `isAdmin === false`. An
 *    `isAdmin` gate hides this control from precisely the population whose
 *    instance default it exists to manage.
 * 3. A SUCCESSFUL WRITE APPLIES LIVE. `defaultUnitPrefs` is React state
 *    populated only inside `AuthContext.loadUser`, and nothing re-reads it after
 *    a settings write, so in `auth_mode=none` every mounted consumer would keep
 *    rendering the old default until the page was reloaded. The retiring gallon
 *    control did not have this problem because it wrote a subscribed store.
 *
 * ★ THE REAL `AuthProvider` IS MOUNTED, NOT A MOCK, and that is what makes (2)
 * and (3) testable at all. Mocking `useAuth` would let this file assert that the
 * card reads two booleans it was handed, which is a statement about the mock.
 * The gate is `isAdmin || authMode === 'none'` and BOTH come from one
 * `/settings/public` payload plus one `/auth/me`, so the arrangement here is the
 * payload, and (3) is unfakeable: the probe below is a SEPARATE component
 * reading `useUnitPreference()`, so the card's own optimistic state cannot
 * satisfy it.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { IMPERIAL_UNITS, METRIC_UNITS, UK_IMPERIAL_UNITS } from '@/__tests__/factories'
import { UNIT_OPTION_LABELS, type UnitSet } from '@/types/units'

vi.mock('@/services/api', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn() },
  setCSRFToken: vi.fn(),
  getCSRFToken: vi.fn(),
  clearCSRFToken: vi.fn(),
  setApiAuthMode: vi.fn(),
}))

// Every label on this card is a translation key, and a card whose heading
// renders the raw key is the failure `validate:i18n-usage` blocks on. Resolving
// through the app's own i18next instance is what lets the cases below assert
// English rather than key echoes.
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

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import i18n from '@/i18n'
import api from '@/services/api'
import { AuthProvider, useAuth } from '@/contexts/AuthContext'
import { useUnitPreference } from '@/hooks/useUnitPreference'
import InstanceUnitDefaultsCard from '../InstanceUnitDefaultsCard'

const mockedApi = vi.mocked(api)

/** Resolve a key the way the card does, so the queries below cannot drift. */
function label(key: string): string {
  return i18n.t(key.includes(':') ? key : `settings:${key}`)
}

/** The settings key the instance default lives under. */
const KEY = 'default_unit_prefs'

/**
 * Arrange `/settings/public` and `/auth/me` for one instance shape.
 *
 * `defaults` is served as the JSON STRING the backend actually stores, not as a
 * nested object: both backend writers store `json.dumps(...)` and the route
 * hands that string back untouched, so a test that served an object would be
 * arranging a payload no instance produces.
 */
function serveInstance(options: {
  authMode: string
  defaults: UnitSet | null
  admin?: boolean
}): void {
  let served = options.defaults
  mockedApi.get.mockImplementation((url: string) => {
    if (url === '/settings/public') {
      const settings = [
        { key: 'auth_mode', value: options.authMode },
        ...(served === null ? [] : [{ key: KEY, value: JSON.stringify(served) }]),
      ]
      return Promise.resolve({ data: { settings } })
    }
    if (url === '/auth/me') {
      return Promise.resolve({ data: { id: 1, username: 'a', is_admin: options.admin === true } })
    }
    return Promise.resolve({ data: {} })
  })
  // A successful write changes what the NEXT read returns, which is what makes
  // the live-apply case below fail against a card that writes and stops.
  mockedApi.post.mockImplementation((url: string, body: unknown) => {
    if (url === '/settings/batch') {
      const raw = (body as { settings: Record<string, string> }).settings[KEY]
      if (raw !== undefined) served = JSON.parse(raw) as UnitSet
    }
    return Promise.resolve({ data: { settings: [], total: 0 } })
  })
}

/**
 * A separate consumer of the resolved units, mounted beside the card.
 *
 * It also reports `loading`, which is the provider's own settle signal: it
 * flips false in `loadUser`'s `finally`, on the failure path as well as the
 * success one. Without it a case asserting the card's ABSENCE could not tell
 * "hidden because the fetch failed" from "not rendered yet".
 */
function UnitsProbe(): React.ReactElement {
  const { units } = useUnitPreference()
  const { loading } = useAuth()
  return (
    <>
      <span data-testid="probe">{units.volume}</span>
      <span data-testid="auth-loading">{String(loading)}</span>
    </>
  )
}

/** Mount the card (and the probe) inside a real AuthProvider. */
function renderCard(): void {
  render(
    <AuthProvider>
      <InstanceUnitDefaultsCard />
      <UnitsProbe />
    </AuthProvider>,
  )
}

/** The card's own region, so a second units editor on the screen cannot match. */
function card(): HTMLElement {
  return screen.getByRole('region', { name: label('units.instanceDefault') })
}

/** Click a preset inside the card and accept the confirmation it shows first. */
async function choosePreset(key: 'units.imperial' | 'units.metric'): Promise<void> {
  await userEvent.click(within(card()).getByRole('button', { name: label(key) }))
  await userEvent.click(screen.getByRole('button', { name: label('units.presetConfirmAction') }))
}

/** The body of the one batch write the card sent. */
function writtenSet(): unknown {
  const call = mockedApi.post.mock.calls.find(([url]) => url === '/settings/batch')
  if (call === undefined) throw new Error('the card sent no batch write')
  const raw = (call[1] as { settings: Record<string, string> }).settings[KEY]
  // The row's value is a JSON STRING, not a nested object. Asserted here rather
  // than left to `JSON.parse` throwing, because an object would parse-fail with
  // a message about the wrong thing.
  expect(typeof raw).toBe('string')
  return JSON.parse(raw)
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  window.dispatchEvent(new Event('storage'))
  mockedApi.put.mockResolvedValue({ data: {} })
})

describe('InstanceUnitDefaultsCard: who may see it', () => {
  it('★ shows to every client on an auth_mode=none instance, where isAdmin is false', async () => {
    // The population the control exists for. `AuthContext` never loads a user
    // in this mode, so `isAdmin` is false and an `isAdmin` gate hides the
    // instance default from the only people who can set it.
    serveInstance({ authMode: 'none', defaults: IMPERIAL_UNITS })
    renderCard()

    expect(await screen.findByRole('region', { name: label('units.instanceDefault') })).toBeTruthy()
  })

  it('shows to an admin when auth is enabled', async () => {
    serveInstance({ authMode: 'local', defaults: IMPERIAL_UNITS, admin: true })
    renderCard()

    expect(await screen.findByRole('region', { name: label('units.instanceDefault') })).toBeTruthy()
  })

  it('★ is not offered when /settings/public never answered, where the gate reads OPEN', async () => {
    // ★ THE FAILURE THAT LOOKS LIKE A CONFIGURED INSTANCE. `authMode`
    // initialises to 'none' and `defaultUnitPrefs` to null, so a boot fetch
    // that throws leaves `isAdmin || authMode === 'none'` TRUE and the card
    // falling back to `basePresetFor('imperial')` exactly as it does for an
    // instance that published nothing. Those two states are not the same
    // state: `UnitSetEditor`'s Custom button fires `onSelect` immediately with
    // no confirmation, so on a UK or metric `auth_mode=none` instance whose
    // fetch failed, an admin opening the per-quantity grid would write US
    // imperial as the instance-wide default for everyone, having chosen
    // nothing. The mirror is every other case in this file: the same gate lets
    // the card through the moment the payload lands.
    mockedApi.get.mockRejectedValue(new Error('network down'))
    renderCard()

    await waitFor(() => expect(screen.getByTestId('auth-loading').textContent).toBe('false'))
    expect(screen.queryByRole('region', { name: label('units.instanceDefault') })).toBeNull()
  })

  it('★ is not offered to a non-admin, whose write the backend would refuse', async () => {
    serveInstance({ authMode: 'local', defaults: IMPERIAL_UNITS, admin: false })
    renderCard()

    // The probe settles only after `/settings/public` and `/auth/me` have both
    // resolved, so the absence below is read AFTER the gate has its answer
    // rather than before the provider has loaded anything.
    await waitFor(() => expect(screen.getByTestId('probe').textContent).toBe('gal_us'))
    expect(screen.queryByRole('region', { name: label('units.instanceDefault') })).toBeNull()
  })
})

describe('InstanceUnitDefaultsCard: reading the stored row back', () => {
  it('highlights the preset the instance actually publishes', async () => {
    serveInstance({ authMode: 'none', defaults: METRIC_UNITS })
    renderCard()

    await waitFor(() =>
      expect(
        within(card()).getByRole('button', { name: label('units.metric') }),
      ).toHaveAttribute('aria-pressed', 'true'),
    )
    expect(within(card()).getByRole('button', { name: label('units.imperial') })).toHaveAttribute(
      'aria-pressed',
      'false',
    )
  })

  it('★ shows a UK-gallon instance its own per-quantity set, not a preset', async () => {
    // `presetTagFor` calls this set `custom`, because both canonical presets are
    // written with `secondary_gallon='us'`. A card that read the tag off
    // anything but the published set would show Imperial and hide the grid.
    serveInstance({ authMode: 'none', defaults: UK_IMPERIAL_UNITS })
    renderCard()

    const volume = await waitFor(() =>
      within(card()).getByLabelText(label(UNIT_OPTION_LABELS.volume.labelKey)),
    )
    expect(volume).toHaveValue('gal_uk')
  })
})

describe('InstanceUnitDefaultsCard: the write', () => {
  it('★ upserts through the batch route, which the single-key PUT cannot do', async () => {
    // The row is ABSENT here, which is the case the backend fallback exists for
    // and the one `PUT /settings/{key}` answers with a 404.
    serveInstance({ authMode: 'none', defaults: null })
    renderCard()

    await waitFor(() => expect(screen.getByTestId('probe').textContent).toBe('gal_us'))
    await choosePreset('units.metric')

    await waitFor(() => expect(mockedApi.post).toHaveBeenCalled())
    expect(mockedApi.post.mock.calls[0][0]).toBe('/settings/batch')
    expect(mockedApi.put).not.toHaveBeenCalled()
  })

  it('★ sends the complete set as a JSON string under the settings key', async () => {
    serveInstance({ authMode: 'none', defaults: IMPERIAL_UNITS })
    renderCard()

    await waitFor(() => expect(screen.getByTestId('probe').textContent).toBe('gal_us'))
    await choosePreset('units.metric')

    // Every one of the eleven fields, because `parse_default_unit_prefs`
    // degrades WHOLE: a partial set stored here reverts every anonymous client
    // to the imperial fallback, and the row is the only thing that says
    // otherwise.
    await waitFor(() => expect(writtenSet()).toStrictEqual(METRIC_UNITS))
  })

  it('★ applies to a mounted consumer without a reload', async () => {
    // `defaultUnitPrefs` is populated only inside `AuthContext.loadUser`.
    // Without a reload of the public settings after the write, every mounted
    // consumer on an `auth_mode=none` instance keeps rendering the old default
    // until the page is refreshed, and the probe is a SEPARATE component so the
    // card's own optimistic state cannot stand in for it.
    serveInstance({ authMode: 'none', defaults: IMPERIAL_UNITS })
    renderCard()

    await waitFor(() => expect(screen.getByTestId('probe').textContent).toBe('gal_us'))

    await choosePreset('units.metric')

    await waitFor(() => expect(screen.getByTestId('probe').textContent).toBe('L'))
  })
})

// ★ THE "has English for every key it renders" CASE IS DELETED, and deleting it
// is the fix rather than the shortcut. It listed four keys by hand and asserted
// each resolved, which `scripts/validate-i18n-usage.ts` already derives from
// every literal translate call in `src/` and blocks CI on. Unlike that gate the
// list was a FLOOR: a fifth key added to this card would never appear in it, so
// the case would keep passing while the thing it claimed to check went unmet,
// and its name promised "every key it renders". The gate is the receipt; the
// card's copy resolving through the real i18next instance is still exercised by
// every query above, all of which go through `label()`.
