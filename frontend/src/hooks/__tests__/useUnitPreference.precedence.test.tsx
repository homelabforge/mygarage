/**
 * The four-rung precedence, one test per rung boundary.
 *
 * Highest wins:
 *   1. an authenticated user's `resolved_units`;
 *   2. an explicit anonymous choice, meaning the `unit_preference` localStorage
 *      key is PRESENT and holds a value the app recognises;
 *   3. `default_unit_prefs` from `/settings/public`;
 *   4. imperial, which nothing post-093 should reach.
 *
 * Rung 3 did not exist before this change: the hook went straight from an
 * authenticated user to `localStorage.getItem('unit_preference') || 'imperial'`,
 * so an anonymous visitor on a metric-default instance got imperial no matter
 * what the admin had configured.
 *
 * ★ The ordering of 2 against 3 is the correction round 1 got wrong, and it is
 * not a detail. `default_unit_prefs` is a DEFAULT: what you get before you
 * choose, not something that overrides a choice already made. On an
 * `auth_mode=none` instance the `unit_preference` key is the ONLY units control
 * that exists (`SettingsSystemTab.tsx` writes it for a client with no account,
 * and `ProtectedRoute` lets `auth_mode=none` reach `/settings`), while migration
 * 093 seeds `default_unit_prefs` to the imperial or UK-imperial preset and never
 * to metric. Letting the default outrank the key made metric unreachable on
 * those instances, with the toggle still highlighting the choice it could no
 * longer honour.
 *
 * Every test pins the rung ABOVE against a DIFFERENT answer on the rung below,
 * so a hook that consulted the wrong one cannot pass.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import {
  IMPERIAL_UNITS,
  METRIC_UNITS,
  UK_IMPERIAL_UNITS,
  makeUnitSet,
  makeUser,
  type User,
} from '@/__tests__/factories'
import type { UnitSet } from '@/types/units'
import { binarySystemFor } from '@/types/units'
import { gallonStandardFor } from '@/utils/publicUnitDefaults'
import { setUnitPrefs } from '@/utils/unitPrefsStore'

/**
 * Let the browser preference store re-read `localStorage`.
 *
 * ★ Rung 2 is no longer a `localStorage.getItem` during render. The store
 * parses ONCE at module load and holds the object, because
 * `useSyncExternalStore` throws if `getSnapshot` returns a fresh one per
 * render, so a `setItem` in a test body is invisible to a store that has
 * already parsed. A `storage` event is how a later write reaches it in
 * production, and dispatching one here means these arrangements still exercise
 * the real path, including the one-shot migration off the legacy keys.
 */
function reloadBrowserPrefs(): void {
  window.dispatchEvent(new Event('storage'))
}

const h = vi.hoisted(() => ({
  user: null as User | null,
  defaultUnitPrefs: null as UnitSet | null,
}))

vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({
    user: h.user,
    isAuthenticated: h.user !== null,
    defaultUnitPrefs: h.defaultUnitPrefs,
  }),
}))

import { useUnitPreference } from '../useUnitPreference'

describe('useUnitPreference precedence', () => {
  beforeEach(() => {
    localStorage.clear()
    h.user = null
    h.defaultUnitPrefs = null
    // ★ A pin on the module-level gallon store used to sit here, so that a
    // rung-1 answer of 'uk' could only have come from the set under test. Phase
    // 4 task 5 retired that store: the instance-wide gallon is read from
    // `defaultUnitPrefs` now, which `h` above already resets.
    // `imperial_gallon_standard` survives only as one of the three LEGACY keys
    // `unitPrefsStore.migrateLegacy` folds in, so the `localStorage.clear()`
    // below is what pins it, and the cases that still exercise it write the raw
    // key.
    localStorage.clear()
    reloadBrowserPrefs()
  })

  describe('rung 1 beats rung 2', () => {
    it('an account beats an explicit anonymous choice left in the browser', () => {
      localStorage.setItem('unit_preference', 'metric')
      reloadBrowserPrefs()
      h.user = makeUser({ unit_preference: 'imperial', resolved_units: IMPERIAL_UNITS })

      const { result } = renderHook(() => useUnitPreference())

      expect(result.current.system).toBe('imperial')
    })

    it("the account's showBoth beats the browser key", () => {
      localStorage.setItem('show_both_units', 'false')
      reloadBrowserPrefs()
      h.user = makeUser({ show_both_units: true })

      const { result } = renderHook(() => useUnitPreference())

      expect(result.current.showBoth).toBe(true)
    })
  })

  describe('rung 1 beats rung 3', () => {
    it('an imperial account stays imperial on a metric-default instance', () => {
      h.user = makeUser({ unit_preference: 'imperial', resolved_units: IMPERIAL_UNITS })
      h.defaultUnitPrefs = METRIC_UNITS

      const { result } = renderHook(() => useUnitPreference())

      expect(result.current.system).toBe('imperial')
    })

    it('a metric account stays metric on an imperial-default instance', () => {
      h.user = makeUser({ unit_preference: 'metric', resolved_units: METRIC_UNITS })
      h.defaultUnitPrefs = IMPERIAL_UNITS

      const { result } = renderHook(() => useUnitPreference())

      expect(result.current.system).toBe('metric')
    })

    it("the account's own gallon flavour beats the instance default's", () => {
      h.user = makeUser({
        unit_preference: 'custom',
        resolved_units: makeUnitSet({ volume: 'gal_uk', secondary_gallon: 'uk' }),
      })
      h.defaultUnitPrefs = IMPERIAL_UNITS // gal_us

      const { result } = renderHook(() => useUnitPreference())

      expect(result.current.gallonStandard).toBe('uk')
    })

    it("★ an account with no resolved units takes the INSTANCE default's gallon", () => {
      // A browser holding a bundle against an older backend, so rung 1 has a
      // preference and no set. It used to fall to a `localStorage` cache of
      // `imperial_gallon_standard`; phase 4 task 5 retired that cache, and this
      // now reads the same instance value from the same `/settings/public`
      // payload, one boot fresher and eleven quantities wider.
      h.user = makeUser({ resolved_units: undefined })
      h.defaultUnitPrefs = UK_IMPERIAL_UNITS

      const { result } = renderHook(() => useUnitPreference())

      expect(result.current.gallonStandard).toBe('uk')
    })

    it('and follows it in the other direction too', () => {
      // The mirror, so the case above cannot pass on a hardcoded 'uk'.
      h.user = makeUser({ resolved_units: undefined })
      h.defaultUnitPrefs = IMPERIAL_UNITS // gal_us

      const { result } = renderHook(() => useUnitPreference())

      expect(result.current.gallonStandard).toBe('us')
    })
  })

  describe('rung 2 beats rung 3: a choice already made outranks a default', () => {
    it('an anonymous metric choice survives an imperial instance default', () => {
      // ★ The `auth_mode=none` household. This is the only units control such an
      // instance has, and migration 093 can only ever seed imperial or
      // UK-imperial, so losing here makes metric permanently unreachable.
      localStorage.setItem('unit_preference', 'metric')
      reloadBrowserPrefs()
      h.defaultUnitPrefs = IMPERIAL_UNITS

      const { result } = renderHook(() => useUnitPreference())

      expect(result.current.system).toBe('metric')
    })

    it('an anonymous imperial choice survives a metric instance default', () => {
      localStorage.setItem('unit_preference', 'imperial')
      reloadBrowserPrefs()
      h.defaultUnitPrefs = METRIC_UNITS

      const { result } = renderHook(() => useUnitPreference())

      expect(result.current.system).toBe('imperial')
    })

    it('★ a browser that CHOSE its gallon flavour keeps it against the instance', () => {
      // ★ THE OVER-APPLICATION GUARD for the two cases above, and the line
      // between them is what "a choice" means. `setUnitPrefs` is the only
      // writer of a set to `unit_prefs`, and a client reaches it by working the
      // Settings controls, so this set really is a per-quantity choice and rung
      // 2 outranks the instance for all eleven of it. Recomposing every rung-2
      // set from the instance flavour, rather than only a migrated one, fails
      // exactly here.
      h.defaultUnitPrefs = IMPERIAL_UNITS // gal_us
      setUnitPrefs({
        units: UK_IMPERIAL_UNITS,
        unit_preference: 'custom',
        show_both_units: false,
      })

      const { result } = renderHook(() => useUnitPreference())

      expect(result.current.gallonStandard).toBe('uk')
      expect(result.current.units.volume).toBe('gal_uk')
    })

    it('★ a migrated browser keeps the dead cache only when the instance publishes nothing', () => {
      // The failed-`/settings/public` client. There is no instance flavour to
      // follow, so the key's last word is the best answer available and is the
      // same one this browser rendered before the upgrade. A recomposition that
      // ignored the absent default would answer 'us' here from the imperial
      // preset and silently convert a UK household's fuel log.
      localStorage.setItem('unit_preference', 'imperial')
      localStorage.setItem('imperial_gallon_standard', 'uk')
      reloadBrowserPrefs()
      h.defaultUnitPrefs = null

      const { result } = renderHook(() => useUnitPreference())

      expect(result.current.gallonStandard).toBe('uk')
    })

    it('★ a migration-derived set takes its gallon flavour from the INSTANCE, not the dead cache', () => {
      localStorage.setItem('unit_preference', 'imperial')
      localStorage.setItem('imperial_gallon_standard', 'us')
      reloadBrowserPrefs()
      h.defaultUnitPrefs = UK_IMPERIAL_UNITS

      const { result } = renderHook(() => useUnitPreference())

      expect(result.current.gallonStandard).toBe('uk')
    })

    it('and the mirror, so it cannot pass on a hardcoded flavour', () => {
      localStorage.setItem('unit_preference', 'imperial')
      localStorage.setItem('imperial_gallon_standard', 'uk')
      reloadBrowserPrefs()
      h.defaultUnitPrefs = IMPERIAL_UNITS

      const { result } = renderHook(() => useUnitPreference())

      expect(result.current.gallonStandard).toBe('us')
    })

    it('an unrecognised stored value is noise, not a choice, and falls through', () => {
      // `storedSystem || 'imperial'` used to hand this straight back as a
      // UnitSystem, a value the type says cannot exist. A key the app cannot
      // read is not a recorded choice.
      localStorage.setItem('unit_preference', 'furlongs')
      reloadBrowserPrefs()
      h.defaultUnitPrefs = METRIC_UNITS

      const { result } = renderHook(() => useUnitPreference())

      expect(result.current.system).toBe('metric')
    })
  })

  describe('rung 3: the instance default, for a browser that never chose', () => {
    it('a metric instance default applies when the browser holds no choice', () => {
      // The shipped defect this task exists to fix, and the corrected ordering
      // does not weaken it: no key means no choice, so the default answers.
      h.defaultUnitPrefs = METRIC_UNITS

      const { result } = renderHook(() => useUnitPreference())

      expect(result.current.system).toBe('metric')
    })

    it('a UK-gallon instance default answers with its own gallon', () => {
      h.defaultUnitPrefs = makeUnitSet({ volume: 'gal_uk', secondary_gallon: 'uk' })

      const { result } = renderHook(() => useUnitPreference())

      expect(result.current.gallonStandard).toBe('uk')
    })

    it('a litre instance default takes its gallon flavour from secondary_gallon', () => {
      h.defaultUnitPrefs = makeUnitSet({ volume: 'L', secondary_gallon: 'uk' })

      const { result } = renderHook(() => useUnitPreference())

      expect(result.current.gallonStandard).toBe('uk')
    })

    it('still reads showBoth from the browser, which the unit set does not publish', () => {
      // ★ The discriminating case for a MODIFIER with no units rung: this
      // browser set show-both and never chose units, so the store holds the
      // modifier with a null `units` and the instance default still answers.
      localStorage.setItem('show_both_units', 'true')
      reloadBrowserPrefs()
      h.defaultUnitPrefs = METRIC_UNITS

      const { result } = renderHook(() => useUnitPreference())

      // Anchored to rung 3 actually being the rung taken, so this cannot pass
      // by reading the same browser key from rung 4.
      expect(result.current.system).toBe('metric')
      expect(result.current.showBoth).toBe(true)
    })
  })

  describe('rung 4, which nothing post-093 should reach', () => {
    it('falls back to imperial when neither the browser nor the instance answers', () => {
      const { result } = renderHook(() => useUnitPreference())

      expect(result.current.system).toBe('imperial')
    })

    it('★ ignores the retired gallon cache key, which no longer feeds any rung', () => {
      // The key is read by `migrateLegacy` only when a legacy `unit_preference`
      // sits beside it. Alone it is not a choice, so rung 2 stays empty, rung 3
      // has no default, and rung 4 answers with the imperial preset's own
      // gallon. Before task 5 this same key fed a subscribed cache rung 4 read.
      localStorage.setItem('imperial_gallon_standard', 'uk')
      reloadBrowserPrefs()

      const { result } = renderHook(() => useUnitPreference())

      expect(result.current.system).toBe('imperial')
      expect(result.current.gallonStandard).toBe('us')
    })
  })
})

/**
 * The resolved `UnitSet` the hook now publishes alongside the binary system.
 *
 * `useUnitFormat()` closes over this, so every rung has to produce a complete
 * set, and the set has to AGREE with the `system` and `gallonStandard` the same
 * call returns. Two independently derived answers on one screen is the failure
 * this workstream keeps finding, so the agreement is asserted at every rung
 * rather than assumed.
 */
describe('the resolved unit set', () => {
  // Its own reset, not the outer suite's: `h` is module-scoped and the browser
  // preference store is a module singleton, so a leftover user from the block
  // above wins rung 1 here and every rung-2/3/4 assertion below passes or fails
  // for the wrong reason.
  beforeEach(() => {
    localStorage.clear()
    h.user = null
    h.defaultUnitPrefs = null
    reloadBrowserPrefs()
  })

  it('rung 1: hands an account its own set through, overrides and all', () => {
    // A per-quantity set no preset can produce: metric everything, imperial
    // tread. A hook that rebuilt the set from the binary system would answer
    // 'mm' here, and a hook that rebuilt it from the imperial preset 'psi'.
    const resolved = makeUnitSet({ tread: 'in32' })
    h.user = makeUser({ unit_preference: 'custom', resolved_units: resolved })

    const { result } = renderHook(() => useUnitPreference())

    expect(result.current.units.tread).toBe('in32')
    expect(result.current.units.pressure).toBe('kpa')
    expect(result.current.units.volume).toBe('L')
  })

  it('rung 1: falls back to a preset when a stale bundle has no resolved set', () => {
    h.defaultUnitPrefs = UK_IMPERIAL_UNITS
    h.user = makeUser({ unit_preference: 'imperial', resolved_units: undefined })

    const { result } = renderHook(() => useUnitPreference())

    expect(result.current.units.volume).toBe('gal_uk')
    expect(result.current.units.tread).toBe('in32')
  })

  it('rung 2: takes the system from the legacy key and the flavour from the instance', () => {
    // The two halves of a migrated record come from different places, so this
    // pins each against a source that disagrees with it: the instance is
    // imperial and the browser renders litres, the cache says US and the client
    // gets UK. A hook that read either half from the wrong one fails here.
    localStorage.setItem('unit_preference', 'metric')
    localStorage.setItem('imperial_gallon_standard', 'us')
    reloadBrowserPrefs()
    h.defaultUnitPrefs = UK_IMPERIAL_UNITS

    const { result } = renderHook(() => useUnitPreference())

    expect(result.current.units.volume).toBe('L')
    expect(result.current.units.secondary_gallon).toBe('uk')
  })

  it('rung 3: hands the instance default through, overrides and all', () => {
    h.defaultUnitPrefs = makeUnitSet({ pressure: 'bar', tread: 'in32' })

    const { result } = renderHook(() => useUnitPreference())

    expect(result.current.units.pressure).toBe('bar')
    expect(result.current.units.tread).toBe('in32')
  })

  it('rung 4: falls back to the imperial preset whole, gallon included', () => {
    // The same degradation `parse_default_unit_prefs` applies on the server for
    // an unreadable row. Nothing above this rung published a set, so there is
    // no instance flavour to carry and no cache left to read one from.
    const { result } = renderHook(() => useUnitPreference())

    expect(result.current.units.volume).toBe('gal_us')
    expect(result.current.units.consumption).toBe('mpg_us')
  })

  it('agrees with the system and gallon standard it returns, at every rung', () => {
    const cases: Array<{ rung: string; arrange: () => void }> = [
      {
        rung: '1',
        arrange: () => {
          h.user = makeUser({
            unit_preference: 'custom',
            resolved_units: makeUnitSet({ volume: 'gal_uk', secondary_gallon: 'uk' }),
          })
        },
      },
      {
        rung: '2',
        arrange: () => {
          localStorage.setItem('unit_preference', 'metric')
          localStorage.setItem('imperial_gallon_standard', 'uk')
          reloadBrowserPrefs()
        },
      },
      { rung: '3', arrange: () => { h.defaultUnitPrefs = METRIC_UNITS } },
      // Rung 4 IS the reset state: no account, no browser choice, no instance
      // default. Arranging nothing is what reaches it.
      { rung: '4', arrange: () => {} },
    ]

    for (const { rung, arrange } of cases) {
      localStorage.clear()
      h.user = null
      h.defaultUnitPrefs = null
      reloadBrowserPrefs()
      arrange()

      const { result } = renderHook(() => useUnitPreference())

      expect(binarySystemFor(result.current.units.volume), `rung ${rung}`).toBe(
        result.current.system
      )
      expect(gallonStandardFor(result.current.units), `rung ${rung}`).toBe(
        result.current.gallonStandard
      )
    }
  })
})

/**
 * Rung 2 holding a full per-quantity set, which is what the browser store adds.
 *
 * Before it, a client with no account held `imperial | metric` and rung 2
 * expanded that through a preset, so a per-quantity choice was unrepresentable
 * for exactly the population that cannot use the account path.
 */
describe('an anonymous per-quantity choice', () => {
  beforeEach(() => {
    localStorage.clear()
    h.user = null
    h.defaultUnitPrefs = null
    reloadBrowserPrefs()
  })

  it('renders an anonymous custom set exactly, not the nearest preset', () => {
    // Metric everything but imperial pressure and tread: no preset produces it.
    // The instance default is pinned to the metric preset, which is what rung 2
    // used to collapse this to, so 'kpa' and 'mm' here would mean the set was
    // rebuilt from a binary system rather than read.
    h.defaultUnitPrefs = METRIC_UNITS
    setUnitPrefs({
      units: makeUnitSet({ pressure: 'psi', tread: 'in32' }),
      unit_preference: 'custom',
      show_both_units: false,
    })

    const { result } = renderHook(() => useUnitPreference())

    expect(result.current.units.pressure).toBe('psi')
    expect(result.current.units.tread).toBe('in32')
    expect(result.current.units.volume).toBe('L')
    expect(result.current.system).toBe('metric')
  })

  it('re-renders a mounted consumer when the store changes', () => {
    // Nothing subscribed to the browser's preference before this change, so a
    // component that had already mounted went on rendering the units it read at
    // mount until something else re-rendered it.
    h.defaultUnitPrefs = METRIC_UNITS

    const { result } = renderHook(() => useUnitPreference())
    expect(result.current.units.pressure).toBe('kpa')

    act(() => {
      setUnitPrefs({
        units: makeUnitSet({ pressure: 'psi' }),
        unit_preference: 'custom',
        show_both_units: false,
      })
    })

    expect(result.current.units.pressure).toBe('psi')
  })
})
