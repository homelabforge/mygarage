/**
 * Copy that names a unit must name the READER'S unit. RESOLVED PROSE.
 *
 * ★ WHY THIS FILE EXISTS. `setup.ts` mocks react-i18next with
 * `t: (key) => key`, so every existing test reads `'events.card.milesBefore'`
 * and calls it correct. The defect was entirely in the STRING that key
 * resolves to: "miles before", shown to a kilometre account beside a number it
 * had typed in kilometres. A test that never resolves a key cannot see that,
 * and a test written against the mock would CERTIFY it. So this file resolves
 * against the real bundles on disk and asserts what a reader actually sees.
 *
 * ★ THE BUNDLE LIST IS ENUMERATED FROM DISK, NEVER TYPED. There are seven
 * bundles (`src/locales/en` plus six under `public/locales`), and this task's
 * own brief was handed six by a controller who had missed Polish, while
 * `CLAUDE.md` makes the same off-by-one with a different language. A hand-typed
 * list is a floor; a directory listing is not. The count is asserted, so a walk
 * that lost the lazy-loaded bundles fails here rather than reporting six clean
 * languages it never opened.
 *
 * ★ AND EVERY FIXED KEY IS ASSERTED TO EXIST IN `en`. Renaming a key would
 * otherwise empty this file's subject silently: a key nothing resolves has no
 * string to find a unit in, and the guard would pass on copy it never read.
 *
 * ★ THE VOCABULARY IS UNIT NAMES, NOT ODOMETER IDIOMS, following
 * `ReminderForm.distanceCopy.test.tsx`: English "mileage", German
 * "Kilometerstand" and Polish "przebieg" are ordinary words for an odometer
 * READING and make no claim about which unit the number is in. "miles", "MPG"
 * and "gallons" do.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { ReactNode } from 'react'
import { render, screen } from '@testing-library/react'
import { IMPERIAL_UNITS, METRIC_UNITS, makeUser, type User } from './factories'

// ★ Hoisted, because `vi.mock`'s factory runs BEFORE module-level consts are
// initialised and the resolving `t` below needs the bundle walk. A plain
// top-level helper reads as correct and throws "Cannot access before
// initialization" at import time.
const bundleIo = vi.hoisted(() => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { existsSync, readdirSync, readFileSync, statSync } = require('node:fs')
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { join, resolve } = require('node:path')
  const FRONTEND: string = resolve(__dirname, '../..')

  /** Every locale bundle, read off the filesystem. */
  const bundles = (): { lang: string; dir: string }[] => {
    const out: { lang: string; dir: string }[] = []
    for (const base of [join(FRONTEND, 'src/locales'), join(FRONTEND, 'public/locales')]) {
      if (!existsSync(base)) continue
      for (const entry of (readdirSync(base) as string[]).sort()) {
        const dir = join(base, entry)
        if (statSync(dir).isDirectory()) out.push({ lang: entry, dir })
      }
    }
    return out
  }

  /** One key's string in one bundle, or undefined. */
  const lookup = (dir: string, ns: string, path: string): string | undefined => {
    let node: unknown
    try {
      node = JSON.parse(readFileSync(join(dir, `${ns}.json`), 'utf-8'))
    } catch {
      return undefined
    }
    for (const part of path.split('.')) {
      if (node === null || typeof node !== 'object') return undefined
      node = (node as Record<string, unknown>)[part]
    }
    return typeof node === 'string' ? node : undefined
  }

  return { bundles, lookup }
})

const { bundles, lookup } = bundleIo

const langMock = vi.hoisted(() => ({ code: 'en' }))
const auth = vi.hoisted(() => ({ user: null as User | null }))

vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({
    user: auth.user,
    isAuthenticated: auth.user !== null,
    defaultUnitPrefs: null,
  }),
}))

/**
 * A `t` that RESOLVES against the real bundles, falling back to English.
 *
 * Mirrors i18next closely enough for this subject: the namespace comes from a
 * `ns:` prefix or from the namespace the component under test opens, a key the
 * language lacks falls back to English exactly as i18next does, and
 * `{{name}}` placeholders interpolate.
 */
vi.mock('react-i18next', () => {
  // `bundleIo` itself, not the destructured names below it: `vi.mock` factories
  // are hoisted above every plain `const` in this file, `vi.hoisted` ones
  // included in their destructured form.
  const dirs = new Map(bundleIo.bundles().map((b) => [b.lang, b.dir]))
  const t = (key: string, options?: Record<string, unknown>): string => {
    const [ns, path] = key.includes(':') ? key.split(':') : [defaultNs.value, key]
    const own = dirs.get(langMock.code)
    const value =
      (own === undefined ? undefined : bundleIo.lookup(own, ns, path)) ??
      bundleIo.lookup(dirs.get('en')!, ns, path)
    if (value === undefined) return key
    return value.replace(/\{\{(\w+)\}\}/g, (_m, name: string) =>
      options?.[name] === undefined ? '' : String(options[name])
    )
  }
  return {
    useTranslation: (ns?: string) => {
      if (typeof ns === 'string') defaultNs.value = ns
      return { t, i18n: { language: langMock.code, changeLanguage: () => Promise.resolve() } }
    },
    Trans: ({ children }: { children: ReactNode }) => children,
    initReactI18next: { type: '3rdParty', init: () => {} },
  }
})

/** Which namespace a bare key resolves in, set by the component's own call. */
const defaultNs = vi.hoisted(() => ({ value: 'common' }))

import AnalyticsHelpModal from '../components/AnalyticsHelpModal'
import { EventNotificationsCard } from '../components/notifications/EventNotificationsCard'

/**
 * The copy this task made conditional, by namespace and key.
 *
 * A decision list, not a derivation, and labelled as one: which sentences name
 * a unit is a human reading. What IS mechanical is everything around it, the
 * bundle walk and the existence check, so a rename or a lost bundle fails
 * loudly instead of quietly emptying the subject.
 */
const FIXED: readonly { ns: string; key: string }[] = [
  { ns: 'forms', key: 'fuel.mpgTip' },
  { ns: 'forms', key: 'fuel.electricTip' },
  { ns: 'settings', key: 'units.showBothDescription' },
  { ns: 'settings', key: 'events.card.milesBefore' },
  { ns: 'settings', key: 'events.card.milestonesDesc' },
  { ns: 'analytics', key: 'vehicleHelp.costAnalysis.costPerDistanceLabel' },
  { ns: 'analytics', key: 'vehicleHelp.costAnalysis.costPerDistanceDesc' },
  { ns: 'analytics', key: 'vehicleHelp.fuelEconomy.economyCalcLabel' },
  { ns: 'analytics', key: 'vehicleHelp.fuelEconomy.economyCalcDesc' },
  { ns: 'analytics', key: 'vehicleHelp.fuelEconomy.averageEconomyLabel' },
  { ns: 'analytics', key: 'vehicleHelp.fuelEconomy.recentEconomyLabel' },
  { ns: 'analytics', key: 'vehicleHelp.tips.includeOdometer' },
  { ns: 'analytics', key: 'vehicleHelp.tips.markFullTank' },
]

/**
 * The fixed strings that name a unit ON PURPOSE, and why.
 *
 * The gallon-flavour setting's subject IS the gallon, so naming it is correct
 * in the way `units.imperial` and `units.metric` are correct: those are the
 * choices on offer. What the DESCRIPTION used to get wrong was different, and
 * is the same D8 collapse ruling R1 addresses elsewhere: "Used when the unit
 * system is Imperial" told a `{volume:'gal_us', everything-else-metric}`
 * account that its unit system was Imperial, which is not a thing a resolved
 * set has. It now names the QUANTITIES the flavour reaches.
 *
 * ★ The LABEL above it, `units.gallonStandard` ("Imperial gallon standard"),
 * was un-triaged until fix round 1: it sat in neither list, so no decision
 * about it was recorded anywhere, which is the state that lets a defect and a
 * deliberate choice look identical. The ruling is that it is correct as it
 * stands. "Imperial gallon" is that gallon's actual NAME, the same way "US
 * gallon" is (both appear one line below in `units.gallonUs` /
 * `units.gallonUk`); it is not the D8 claim its sibling made, because it says
 * nothing about the reader's unit system. If it ever reads "when your units are
 * Imperial", it moves to `FIXED`.
 *
 * Listed rather than omitted, and each asserted to still name a unit, so the
 * exemptions are exercised instead of being silent holes in `FIXED`.
 */
const NAMES_A_UNIT_DELIBERATELY: readonly { ns: string; key: string }[] = [
  { ns: 'settings', key: 'units.gallonStandardDescription' },
  { ns: 'settings', key: 'units.gallonStandard' },
]

/**
 * Unit NAMES in each supported language, as prose or symbol.
 *
 * ★ CASE-INSENSITIVE, and the flag is the whole finding. The first version of
 * this line had no `i`, and German capitalises every noun, so `meilen?` and
 * `gallonen?` were dead alternatives: review round 1 put
 * `events.card.milesBefore = "Meilen vorher"` and
 * `events.card.milestonesDesc = "Benachrichtigen bei 100k Meilen"` back into
 * `de/settings.json` and this file passed 10 of 10. A guard whose stated
 * subject is cross-bundle coverage and which cannot fire on the language it
 * names alternatives for is not a guard.
 *
 * No term here is a single letter, so `i` costs nothing: the `Löschen`-style
 * false positive that forced case-SENSITIVE matching in
 * `scripts/enumerate-unit-copy.ts` comes from its bare `L` and `m` adapter
 * labels, which this vocabulary does not carry.
 */
const UNIT_NAMES =
  /\b(MPG|GPH|PSI|kWh\/100mi|miles?|milhas?|meilen?|milles?|gallons?|gallonen?|galões?|imperial|metric)\b/iu

beforeEach(() => {
  langMock.code = 'en'
  defaultNs.value = 'common'
  auth.user = null
})

describe('the fixed copy, across every locale bundle on disk', () => {
  it('enumerates the bundles rather than assuming them', () => {
    const found = bundles().map((b) => b.lang)
    // Seven: `en` under src/locales plus six lazy-loaded under public/locales.
    // Asserted so a walk that lost the lazy half fails HERE, rather than
    // reporting six languages of unconditional copy as clean.
    expect(found).toStrictEqual(['en', 'de', 'fr', 'pl', 'pt-BR', 'ru', 'uk'])
  })

  it('still has every fixed key in en, so the guard below has a subject', () => {
    const en = bundles().find((b) => b.lang === 'en')!
    const missing = FIXED.filter(({ ns, key }) => lookup(en.dir, ns, key) === undefined)
    expect(missing).toStrictEqual([])
  })

  it('★ names no unit unconditionally, in any bundle that carries the key', () => {
    const offenders: string[] = []
    const readsByBundle = new Map<string, number>()
    for (const { lang, dir } of bundles()) {
      for (const { ns, key } of FIXED) {
        const value = lookup(dir, ns, key)
        if (value === undefined) continue
        readsByBundle.set(lang, (readsByBundle.get(lang) ?? 0) + 1)
        if (UNIT_NAMES.test(value)) offenders.push(`${lang} ${ns}:${key} -> ${value}`)
      }
    }

    // ★ THE RECEIPT NAMES WHICH BUNDLES CONTRIBUTED, not how many strings were
    // read in total. The first version asserted `read >= FIXED.length`, which
    // `en` satisfies on its own: the offending keys had been DELETED from the
    // six translated bundles, the loop above `continue`s on a missing key, and
    // the cross-bundle leg therefore passed without ever opening a translated
    // file. An emptiness that no translated bundle contributed to is not
    // evidence about translated bundles.
    //
    // `de` and `fr` carry keys again because fix round 1 restored the ones whose
    // meaning never changed; `pl`, `pt-BR`, `ru` and `uk` never translated any
    // of these and carry none, which is stated here rather than hidden behind a
    // total. If a restoration is ever removed, this list shrinks and the test
    // fails before the emptiness below can go vacuous.
    expect([...readsByBundle.keys()].sort()).toStrictEqual(['de', 'en', 'fr'])
    expect(readsByBundle.get('de')).toBeGreaterThan(0)
    expect(readsByBundle.get('fr')).toBeGreaterThan(0)

    expect(offenders).toStrictEqual([])
  })

  it('keeps the gallon-standard pair naming a gallon, and claiming no system', () => {
    const en = bundles().find((b) => b.lang === 'en')!
    for (const { ns, key } of NAMES_A_UNIT_DELIBERATELY) {
      const value = lookup(en.dir, ns, key)
      expect(value, `${ns}:${key}`).toBeDefined()
      // Names the unit the setting is ABOUT...
      expect(UNIT_NAMES.test(value!), `${ns}:${key} names no unit`).toBe(true)
      // ...and neither claims the account has a single "unit system", which is
      // what a resolved set replaced.
      expect(value, `${ns}:${key}`).not.toMatch(/unit system/i)
    }
  })
})

describe('AnalyticsHelpModal names the reader\'s own consumption unit', () => {
  it('★ says MPG to an MPG account', () => {
    auth.user = makeUser({ unit_preference: 'custom', resolved_units: IMPERIAL_UNITS })
    render(<AnalyticsHelpModal isOpen onClose={() => {}} />)

    expect(screen.getByText('MPG Calculation:')).toBeInTheDocument()
    expect(screen.getByText('Average MPG:')).toBeInTheDocument()
    expect(screen.getByText('Recent MPG:')).toBeInTheDocument()
    expect(
      screen.getByText('Mark fuel fill-ups as "full tank" for accurate MPG tracking'),
    ).toBeInTheDocument()
  })

  it('★ says L/100km to an L/100km account, where it used to say MPG', () => {
    auth.user = makeUser({ unit_preference: 'custom', resolved_units: METRIC_UNITS })
    render(<AnalyticsHelpModal isOpen onClose={() => {}} />)

    expect(screen.getByText('L/100km Calculation:')).toBeInTheDocument()
    expect(screen.getByText('Average L/100km:')).toBeInTheDocument()
    expect(screen.getByText('Recent L/100km:')).toBeInTheDocument()
    expect(screen.queryByText('Average MPG:')).not.toBeInTheDocument()
  })

  it('★ never says "Cost Per Mile" or "miles driven" to anyone', () => {
    // The cost-per-distance DENOMINATOR is task 7's decision, so the copy names
    // the quantity rather than pre-empting a unit; what it must not do is keep
    // naming the mile to a reader who does not use one.
    auth.user = makeUser({ unit_preference: 'custom', resolved_units: METRIC_UNITS })
    render(<AnalyticsHelpModal isOpen onClose={() => {}} />)

    expect(screen.getByText('Cost Per Distance:')).toBeInTheDocument()
    expect(screen.queryByText('Cost Per Mile:')).not.toBeInTheDocument()
    expect(
      screen.getByText('Total cost divided by total distance driven (if odometer data is available).'),
    ).toBeInTheDocument()
    expect(
      screen.getByText('Include odometer data for cost-per-distance calculations'),
    ).toBeInTheDocument()
  })
})

describe('EventNotificationsCard names the reader\'s own distance unit', () => {
  const noop = (): void => {}
  const renderCard = (): void => {
    render(
      <EventNotificationsCard
        settings={{ notify_service_due: 'true' }}
        onSettingChange={noop}
        onTextChange={noop}
        saving={false}
        hasEnabledService
      />,
    )
  }

  it('★ says "km before" to a kilometre account, where it said "miles before"', () => {
    auth.user = makeUser({ unit_preference: 'custom', resolved_units: METRIC_UNITS })
    renderCard()

    expect(screen.getByText('km before')).toBeInTheDocument()
    expect(screen.queryByText('miles before')).not.toBeInTheDocument()
  })

  it('says "mi before" to a mile account, so the fix is not a blanket rename', () => {
    auth.user = makeUser({ unit_preference: 'custom', resolved_units: IMPERIAL_UNITS })
    renderCard()

    expect(screen.getByText('mi before')).toBeInTheDocument()
  })

  it('★ no longer claims a milestone magnitude, in miles or at all', () => {
    // It said "(e.g., 100k miles)". The scheduled job fires every 10,000 km
    // (`backend/app/tasks/scheduled.py:187`), so the example was wrong about
    // the unit AND about the number, by a factor of sixteen.
    auth.user = makeUser({ unit_preference: 'custom', resolved_units: IMPERIAL_UNITS })
    renderCard()

    expect(
      screen.getByText('Notify when reaching significant odometer milestones.'),
    ).toBeInTheDocument()
    expect(screen.queryByText(/100k miles/)).not.toBeInTheDocument()
  })
})
