import { describe, it, expect } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { SUPPORTED_LANGUAGES } from '@/constants/i18n'

/**
 * The composed unit description exists, and interpolates, in EVERY shipped locale.
 *
 * ★ WHY A TEST AND NOT A GATE. `validate-translations.ts` treats a MISSING key
 * as a non-blocking warning on purpose (an untranslated key falls back to
 * English while a language is in progress), so shipping this key in `en` alone
 * would leave six languages reading the retired sentence until their next
 * translation pass, and nothing would have said so. Its `interpolation` check
 * IS blocking, but only for a key a language already has. The gap between those
 * two is exactly this key.
 *
 * ★ AND WHY THE LOCALE BUNDLES NEEDED SAYING AT ALL. `validate-reachability.ts`
 * walks textual imports from `src/main.tsx`, and the non-English bundles are
 * fetched by HTTP URL template (`i18n.ts`), so the walker cannot see them.
 * Plan 3b ruling R9 names them explicitly for this reason: the description this
 * file guards exists in seven languages and nothing mechanical would have
 * pointed at six of them.
 *
 * ★ THE COMPONENT MOVED IN PHASE 4 TASK 4, and this file found out by
 * refusing the tree: the two composed sentences now live in
 * `components/settings/UnitPreferencesCard.tsx`, extracted from
 * `SettingsSystemTab.tsx` with the rest of the unit block. Only the path
 * changed; every name below is still read from whatever that path holds.
 *
 * ★ EVERY NAME IS READ, NEVER TRANSCRIBED. The key and the interpolation
 * variable are parsed out of `UnitPreferencesCard.tsx`'s own `t(...)` call, so
 * renaming either one in the component fails here until all seven bundles
 * follow. Transcribing them would recreate the defect one file over: the
 * component could move to `{{unitList}}`, every bundle would keep rendering a
 * raw `{{units}}` to users, and this file would stay green. The language list
 * is read from `SUPPORTED_LANGUAGES` for the same reason.
 *
 * ★ AND THE READ MUST BE UNAMBIGUOUS, which is the third revision of it. The
 * first took the FIRST match and asserted nothing about the rest, so adding any
 * other interpolating `units.*` call silently relocated this whole file onto
 * that other key: with a second call added and the real key dropped from `de`,
 * all 56 tests passed. A missing key is a NON-BLOCKING warning in
 * `validate-translations.ts`, so this file is the only protection six locales
 * have, and a guard that can be moved off its subject by an unrelated edit is
 * not one. The second revision made any second `units.*` call a hard error,
 * which held until task 6b gave the show-both toggle a composed example of its
 * own and this file refused the tree, exactly as designed. The third revision
 * is the fix that refusal asked for: the reader is told WHICH key it is about,
 * so it cannot relocate, and a second call FOR THAT KEY is still a hard error.
 * The variable is still parsed rather than transcribed, so renaming
 * `{{units}}` in the component fails here until all seven bundles follow.
 */

const FRONTEND = resolve(__dirname, '..', '..')
const COMPONENT = resolve(FRONTEND, 'src/components/settings/UnitPreferencesCard.tsx')
const EN_BUNDLE = resolve(FRONTEND, 'src/locales/en/settings.json')
const PUBLIC_LOCALES = resolve(FRONTEND, 'public/locales')

/**
 * The two fixed sentences the composed one replaced.
 *
 * Written out here because they are being DELETED, so there is no source left
 * to read them from. Plan 3b ruling R1: they selected on the binary system,
 * which is collapsed from volume, so a `{volume:'L', distance:'mi',
 * pressure:'psi'}` account was told it uses kilometres and bar.
 */
const RETIRED_KEYS = ['imperialDescription', 'metricDescription'] as const

/** The settings namespace, as one flat object of dotted keys under `units.`. */
type UnitsBlock = Record<string, unknown>

/**
 * The key and interpolation variable a component source renders with.
 *
 * A hard error rather than a skipped assertion when it cannot be read: this
 * whole file derives from that one call, so a failed read means the assertions
 * below would be checking nothing.
 *
 * ★ IT TAKES THE SOURCE AS A STRING so both refusals can be driven directly.
 * They cannot be reached from the real file: a component with no interpolating
 * call, or with two, is a component this guard exists to stop from shipping, so
 * neither state can exist in a tree the suite is allowed to be green on.
 * Deleting the two-call branch therefore left all 57 tests passing, which is a
 * guard that reads as covered and is not. Reading a string instead makes both
 * branches killable by the two cases below, and the one-line wrapper keeps the
 * real file as the subject of everything else.
 *
 * @param source The component source to read.
 * @param where The path to name in a refusal.
 * @returns The `units.*` key and the name inside its `{{...}}` placeholder.
 */
export function contractFromSource(
  source: string,
  where: string,
  key: string
): { key: string; variable: string } {
  const pattern = new RegExp(`\\bt\\(\\s*'units\\.${key}'\\s*,\\s*\\{\\s*([A-Za-z]+):`, 'g')
  const matches = [...source.matchAll(pattern)]
  if (matches.length === 0) {
    throw new Error(
      `could not find an interpolating t('units.${key}', { ... }) call in ${where}. ` +
        'The unit description is composed ' +
        'from the resolved set (plan 3b R1), so a component that no longer interpolates ' +
        'has either regressed to a fixed string or renamed the call beyond this reader. ' +
        'Either way the locale assertions below would be checking nothing.'
    )
  }
  if (matches.length > 1) {
    throw new Error(
      `${where} now has ${matches.length} interpolating units.${key} calls. This file ` +
        'takes one as its subject, so a second would leave it ambiguous which render the ' +
        'locale assertions below describe, in six locales where a missing key is only a ' +
        'non-blocking warning. Collapse them, or give the second its own reader.'
    )
  }
  return { key, variable: matches[0][1] }
}

/**
 * The composed sentence this file's per-locale assertions are about.
 *
 * NAMED rather than discovered, since task 6b: the Units card now
 * interpolates two `units.*` keys (this one and `showBothDescription`), and a
 * reader that took "the only one" would have to be re-pointed by hand every
 * time the screen grows another. Naming it is what makes relocation
 * impossible; the VARIABLE is still read from the source.
 */
const SUBJECT_KEY = 'resolvedDescription'

/** The same read, against the component this file is actually about. */
function contractFromComponent(): { key: string; variable: string } {
  return contractFromSource(
    readFileSync(COMPONENT, 'utf-8'),
    'src/components/settings/UnitPreferencesCard.tsx',
    SUBJECT_KEY
  )
}

const { key: DESCRIPTION_KEY, variable: DESCRIPTION_VARIABLE } = contractFromComponent()
const PLACEHOLDER = `{{${DESCRIPTION_VARIABLE}}}`

const LANGUAGES = SUPPORTED_LANGUAGES.map((language) => language.code)

/** Where a language's `settings` namespace ships. English is bundled in `src`. */
function bundlePathFor(language: string): string {
  return language === 'en' ? EN_BUNDLE : join(PUBLIC_LOCALES, language, 'settings.json')
}

/** The `units` block of one language's settings bundle. */
function unitsBlockFor(language: string): UnitsBlock {
  const path = bundlePathFor(language)
  const parsed = JSON.parse(readFileSync(path, 'utf-8')) as { units?: UnitsBlock }
  if (parsed.units === undefined) {
    throw new Error(`${path} has no "units" block`)
  }
  return parsed.units
}

describe('the reader this file rests on refuses an unusable component', () => {
  // Neither state can be reached from the real component: one is a regression
  // to a fixed string and the other is the relocation this guard exists to
  // prevent, so both would have to SHIP to be reachable. Driving the reader
  // with a source string is what makes the two refusals killable at all;
  // deleting either branch previously left all 57 tests green.
  const ONE_CALL = "  {t('units.resolvedDescription', { units: summary })}"

  it('accepts exactly one interpolating call for its named key, and reports it', () => {
    expect(contractFromSource(ONE_CALL, 'fixture.tsx', SUBJECT_KEY)).toStrictEqual({
      key: 'resolvedDescription',
      variable: 'units',
    })
  })

  it('refuses a component that no longer interpolates the named key', () => {
    expect(() =>
      contractFromSource("  {t('units.resolvedDescription')}", 'fixture.tsx', SUBJECT_KEY)
    ).toThrow(/could not find an interpolating .* call in fixture\.tsx/)
  })

  it('★ is not relocated by a SIBLING units.* call, which is how it used to break', () => {
    // Task 6b added `units.showBothDescription`, also interpolating, three
    // lines below the subject. A reader that took "the only units.* call"
    // refused the whole tree; one that took the FIRST would have moved every
    // locale assertion onto a key that ships in English alone.
    const sibling = `  {t('units.showBothDescription', { example: 'x' })}\n${ONE_CALL}`
    expect(contractFromSource(sibling, 'fixture.tsx', SUBJECT_KEY)).toStrictEqual({
      key: 'resolvedDescription',
      variable: 'units',
    })
  })

  it('refuses a SECOND interpolating call for the SAME key', () => {
    const two = `${ONE_CALL}\n${ONE_CALL}`
    expect(() => contractFromSource(two, 'fixture.tsx', SUBJECT_KEY)).toThrow(
      /now has 2 interpolating units\.resolvedDescription calls/
    )
  })
})

describe('the show-both description carries its composed example', () => {
  /**
   * The sibling key, read the same way and asserted differently ON PURPOSE.
   *
   * `resolvedDescription` ships translated in all seven bundles, so every one
   * is checked for the placeholder. `showBothDescription` changed MEANING in
   * task 6b (it used to read 'both imperial and metric (e.g., "25 MPG
   * (9.4 L/100km)")', a sentence that is wrong for a reader whose counterpart
   * resolves per quantity), so its six stale translations were removed and
   * those languages fall back to the corrected English. The assertions below
   * are therefore: English must carry the placeholder, and no locale may ship
   * a copy that does NOT, which is the state that would silently drop the
   * example back out of the sentence.
   */
  const SHOW_BOTH_KEY = 'showBothDescription'

  it('interpolates in the component, under a variable read from the source', () => {
    const { variable } = contractFromSource(
      readFileSync(COMPONENT, 'utf-8'),
      'src/components/settings/UnitPreferencesCard.tsx',
      SHOW_BOTH_KEY
    )
    expect(typeof unitsBlockFor('en')[SHOW_BOTH_KEY]).toBe('string')
    expect(unitsBlockFor('en')[SHOW_BOTH_KEY] as string).toContain(`{{${variable}}}`)
  })

  it('is never shipped by a locale without the placeholder', () => {
    const { variable } = contractFromSource(
      readFileSync(COMPONENT, 'utf-8'),
      'src/components/settings/UnitPreferencesCard.tsx',
      SHOW_BOTH_KEY
    )
    const broken = LANGUAGES.filter((language) => {
      const value = unitsBlockFor(language)[SHOW_BOTH_KEY]
      return typeof value === 'string' && !value.includes(`{{${variable}}}`)
    })
    expect(broken).toStrictEqual([])
  })

  it('no longer states the example as a fixed imperial pair, in any locale', () => {
    // "25 MPG (9.4 L/100km)" was the example whichever way round the reader's
    // own counterpart resolves, and a metric account reads the reverse.
    const stale = LANGUAGES.filter((language) => {
      const value = unitsBlockFor(language)[SHOW_BOTH_KEY]
      return typeof value === 'string' && /MPG/.test(value)
    })
    expect(stale).toStrictEqual([])
  })
})

describe('the composed unit description ships in every locale', () => {
  it('checks every language the app can load, and no orphan directory', () => {
    // Both directions. A language in the constant with no directory would be
    // skipped by a disk-driven loop; a directory absent from the constant is
    // translated forever and never fetched. The gate catches the second; this
    // catches the first, which is the one that lets a locale miss this key.
    const shipped = readdirSync(PUBLIC_LOCALES)
      .filter((entry) => statSync(join(PUBLIC_LOCALES, entry)).isDirectory())
      .sort()
    expect(shipped).toStrictEqual(LANGUAGES.filter((code) => code !== 'en').sort())
    expect(LANGUAGES).toContain('en')
  })

  it.each(LANGUAGES)('%s composes the description from the resolved set', (language) => {
    // No `existsSync` guard: an absent bundle makes `readFileSync` throw an
    // ENOENT that already names the path, so the guard could never fail while
    // anything below it passed. An assertion that cannot fail on its own reads
    // as coverage and is not.
    const path = bundlePathFor(language)
    const units = unitsBlockFor(language)
    const description = units[DESCRIPTION_KEY]
    expect(typeof description, `units.${DESCRIPTION_KEY} in ${path}`).toBe('string')
    expect(description as string).toContain(PLACEHOLDER)
  })

  it.each(LANGUAGES)('%s no longer ships either fixed sentence', (language) => {
    const units = unitsBlockFor(language)
    for (const retired of RETIRED_KEYS) {
      expect(Object.keys(units), `units.${retired} survives in ${bundlePathFor(language)}`).not.toContain(retired)
    }
  })
})
