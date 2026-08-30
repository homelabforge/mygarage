/**
 * The volume-total captions name no unit of their own, in every shipped locale.
 *
 * ★ WHAT THIS REPLACED, because the shape matters more than the strings. The
 * propane list and the analytics page each chose between two PROSE captions on
 * a raw `units.volume === 'L'` branch: "Total Liters" or "Total Gallons",
 * translated seven ways. That is a second vocabulary of unit names living in
 * the locale bundles, three lines away from a volume COLUMN header that already
 * interpolated `{{unit}}` from `UNIT_ADAPTERS`, and the two could disagree
 * without anything noticing. Plan 3b task 6 collapsed them onto one
 * `{{unit}}` key each.
 *
 * ★ WHY A TEST AND NOT JUST THE GATE. `validate-units.ts` sees the branch and
 * its baseline count for both files is now zero, which pins the CODE. Nothing
 * pins the STRINGS: a translator writing "Gesamt Liter" for a key whose value
 * is interpolated puts the unit name straight back, in a file no gate reads and
 * against a `t` mock that returns keys. `validate-translations.ts` would not
 * complain either, since the key exists and the placeholder is intact.
 *
 * ★ THE KEYS ARE PARSED OUT OF THE COMPONENTS, never transcribed, for the
 * reason `unitDescriptionLocales.test.ts` gives: transcribing them lets the
 * component move to another key while this file keeps asserting the old one,
 * green and pointless. A read that fails is a hard error, not a skip.
 */

import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { SUPPORTED_LANGUAGES } from '@/constants/i18n'

const FRONTEND = resolve(__dirname, '..', '..')

/**
 * Names of the LITRE and the GALLON, per language.
 *
 * Only the unit's own name. `{{unit}}` is what these captions carry instead,
 * and it resolves through `UnitFormatter.getVolumeUnit`, which reads the same
 * adapter table the column header does.
 */
const VOLUME_UNIT_NAMES: Record<string, RegExp> = {
  en: /\b(lit(?:re|er)s?|gallons?)\b/iu,
  de: /\b(liter[ns]?|gallonen?)\b/iu,
  fr: /\b(litres?|gallons?)\b/iu,
  pl: /\b(litr\w*|galon\w*)\b/iu,
  'pt-BR': /\b(litros?|gal[ãa]o|gal[õo]es)\b/iu,
  ru: /(литр|галлон)/iu,
  uk: /(літр|галон)/iu,
}

/** Which caption lives where: the component that renders it, and its bundle. */
const CAPTIONS = [
  {
    component: 'src/components/PropaneRecordList.tsx',
    namespace: 'vehicles',
    block: 'propaneList',
  },
  {
    component: 'src/pages/Analytics.tsx',
    namespace: 'analytics',
    block: 'vehicle',
  },
] as const

/**
 * The interpolating volume-total key a component renders, read from its source.
 *
 * @param component The component's path, relative to the frontend root.
 * @param block The namespace block the key must live in.
 * @returns The key's leaf name.
 */
function captionKey(component: string, block: string): string {
  const source = readFileSync(resolve(FRONTEND, component), 'utf-8')
  const matches = [
    ...source.matchAll(
      new RegExp(`t\\('${block}\\.(total\\w+)',\\s*\\{\\s*unit:`, 'g')
    ),
  ]
  const names = [...new Set(matches.map((m) => m[1]))]
  if (names.length !== 1) {
    throw new Error(
      `expected exactly one interpolating ${block}.total* caption in ${component}, ` +
        `found ${names.length} (${names.join(', ') || 'none'}). This file derives its ` +
        'subject from that call, so a failed read would leave the assertions below ' +
        'checking nothing.'
    )
  }
  return names[0]
}

/**
 * One key's string in one language's bundle.
 *
 * @param lang The language code.
 * @param namespace The bundle's file stem.
 * @param path The dotted key path.
 * @returns The string, or undefined when the bundle or the key is absent.
 */
function lookup(lang: string, namespace: string, path: string): string | undefined {
  const file =
    lang === 'en'
      ? resolve(FRONTEND, 'src/locales/en', `${namespace}.json`)
      : resolve(FRONTEND, 'public/locales', lang, `${namespace}.json`)
  let node: unknown
  try {
    node = JSON.parse(readFileSync(file, 'utf-8'))
  } catch {
    return undefined
  }
  for (const part of path.split('.')) {
    if (node === null || typeof node !== 'object') return undefined
    node = (node as Record<string, unknown>)[part]
  }
  return typeof node === 'string' ? node : undefined
}

describe('the volume-total captions', () => {
  it('has a unit vocabulary for every shipped language', () => {
    // A language added without a pattern would SKIP every case below while this
    // file still read as covering all of them.
    expect(SUPPORTED_LANGUAGES.map((l) => l.code).sort()).toEqual(
      Object.keys(VOLUME_UNIT_NAMES).sort()
    )
  })

  for (const { component, namespace, block } of CAPTIONS) {
    describe(`${block}, rendered by ${component}`, () => {
      it('is one interpolating key rather than a pair chosen by units.volume', () => {
        const key = captionKey(component, block)
        const source = readFileSync(resolve(FRONTEND, component), 'utf-8')
        expect(key).toMatch(/^total/)
        // The retired pair, by name: neither may come back, in this file or in
        // any bundle. `validate-units.ts` sees the branch; nothing else sees
        // the keys.
        expect(source).not.toContain(`${block}.totalLiters`)
        expect(source).not.toContain(`${block}.totalGallons`)
      })

      it.each(SUPPORTED_LANGUAGES.map((l) => l.code))(
        'carries {{unit}} and names no volume unit in %s',
        (lang) => {
          const key = captionKey(component, block)
          const value = lookup(lang, namespace, `${block}.${key}`)
          expect(value, `${lang} has no ${namespace}:${block}.${key}`).toBeDefined()
          expect(value).toContain('{{unit}}')
          expect(value).not.toMatch(VOLUME_UNIT_NAMES[lang])
          // And the pair it replaced is gone from the bundle, not merely
          // unreferenced: a stale "Total Liters" is the string a future edit
          // reaches for.
          expect(lookup(lang, namespace, `${block}.totalLiters`)).toBeUndefined()
          expect(lookup(lang, namespace, `${block}.totalGallons`)).toBeUndefined()
        }
      )
    })
  }
})
