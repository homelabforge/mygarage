/**
 * The reminder mileage field's own copy must not name a unit. RESOLVED PROSE.
 *
 * ★ WHY THIS FILE EXISTS AT ALL, and it is a hole in the existing coverage
 * rather than a new subject. `setup.ts` mocks react-i18next with
 * `t: (key) => key`, so every other ReminderForm test reads the label as
 * `'reminder.milesUntilDue * (km)'` and calls that correct. The defect was
 * entirely in the STRING that key resolves to: task 3 moved this field onto
 * `units.distance`, so the suffix is now the reader's own unit while the label
 * beside it still said "Miles Until Due" in English and
 * "Quilômetros até o vencimento" in Brazilian Portuguese. A kilometres account
 * read "Miles Until Due (km)"; a Brazilian miles account read the mirror. A
 * test that never resolves a key cannot see either.
 *
 * So this file mocks `t` to resolve against the REAL bundles on disk, one
 * language at a time, and asserts what a reader of that language actually sees.
 *
 * ★ AND IT ASSERTS ON THE RENDERED LABEL, NOT ON A KEY. Naming the key here
 * would let a rename move the guard off its subject: rename the key, leave the
 * string, and a key-shaped test goes green on a component that still says
 * "Miles". The subject is "whatever prose this component puts beside
 * `unit={u.distance.label}`", so that is what is read. The validation message
 * has no rendered handle of its own, so its key is PARSED OUT of the component
 * instead of transcribed, and a component whose shape no longer matches is a
 * hard error rather than a skipped assertion.
 *
 * ★ THE VOCABULARY IS UNIT NAMES, NOT ODOMETER IDIOMS, and the difference is
 * deliberate. German "Kilometerstand", French "kilométrage", Polish "przebieg",
 * Portuguese "quilometragem" and Russian "пробег" are those languages' ordinary
 * words for an odometer READING, exactly as English "mileage" is, and English
 * "mileage" is already used unit-neutrally throughout this app. None of them is
 * a claim about which unit the number is in. "Meilen", "Quilômetros" and "Миль"
 * are, and those are what the patterns below match. The `\b` boundaries are
 * what keeps the two apart: `kilometer` does not match `Kilometerstand`.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { ReactNode } from 'react'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { waitFor } from '@testing-library/react'
import { render } from '../../__tests__/test-utils'
import { SUPPORTED_LANGUAGES } from '@/constants/i18n'
import { binarySystemFor, type UnitSet } from '../../types/units'
import type { Reminder } from '../../types/reminder'

vi.mock('../../hooks/useReminders', () => ({
  useCreateReminder: () => ({ mutateAsync: vi.fn().mockResolvedValue({}) }),
  useUpdateReminder: () => ({ mutateAsync: vi.fn().mockResolvedValue({}) }),
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('../../services/api', () => ({
  default: {
    get: vi.fn().mockResolvedValue({
      data: { usage_unit: 'distance', secondary_usage_enabled: false },
    }),
  },
}))

const unitPrefMock = vi.hoisted(() => ({ units: null as unknown as UnitSet }))
vi.mock('../../hooks/useUnitPreference', () => ({
  useUnitPreference: () => ({
    system: binarySystemFor(unitPrefMock.units.volume),
    showBoth: false,
    units: unitPrefMock.units,
    gallonStandard: unitPrefMock.units.secondary_gallon,
  }),
}))

const langMock = vi.hoisted(() => ({ code: 'en' }))

/** `en` is bundled with the app; every other language is fetched from public/. */
function bundlePath(lang: string, ns: string): string {
  const frontend = resolve(__dirname, '../../..')
  return lang === 'en'
    ? resolve(frontend, 'src/locales/en', `${ns}.json`)
    : resolve(frontend, 'public/locales', lang, `${ns}.json`)
}

/**
 * One key's string in one language, or undefined.
 *
 * @param lang The language code.
 * @param ns The namespace (file stem).
 * @param path The dotted key path inside it.
 * @returns The string, or undefined when the bundle or the key is absent.
 */
function lookup(lang: string, ns: string, path: string): string | undefined {
  let node: unknown
  try {
    node = JSON.parse(readFileSync(bundlePath(lang, ns), 'utf-8'))
  } catch {
    return undefined
  }
  for (const part of path.split('.')) {
    if (node === null || typeof node !== 'object') return undefined
    node = (node as Record<string, unknown>)[part]
  }
  return typeof node === 'string' ? node : undefined
}

/**
 * A `t` that RESOLVES, against the real bundle of whichever language is active.
 *
 * Mirrors i18next closely enough for this subject: the namespace comes from the
 * `ns:` prefix or defaults to the one ReminderForm opens (`forms`), a key the
 * language lacks falls back to English exactly as i18next does, and `{{name}}`
 * placeholders interpolate. A key present in no bundle returns itself, which is
 * what i18next renders too.
 */
vi.mock('react-i18next', () => {
  const t = (key: string, options?: Record<string, unknown>): string => {
    const [ns, path] = key.includes(':') ? key.split(':') : ['forms', key]
    const value = lookup(langMock.code, ns, path) ?? lookup('en', ns, path)
    if (value === undefined) return key
    return value.replace(/\{\{(\w+)\}\}/g, (_m, name: string) =>
      options?.[name] === undefined ? '' : String(options[name])
    )
  }
  return {
    useTranslation: () => ({
      t,
      i18n: { language: langMock.code, changeLanguage: () => Promise.resolve() },
    }),
    Trans: ({ children }: { children: ReactNode }) => children,
    initReactI18next: { type: '3rdParty', init: () => {} },
  }
})

import { IMPERIAL_UNITS, METRIC_UNITS } from '../../__tests__/factories'
import ReminderForm from '../ReminderForm'

/** Litres, but miles: `binarySystemFor('L')` is `'metric'`, so `system` lies. */
const LITRES_MILES: UnitSet = { ...METRIC_UNITS, distance: 'mi', speed: 'mph' }
/** The mirror: gallons, but kilometres. */
const GALLONS_KM: UnitSet = { ...IMPERIAL_UNITS, distance: 'km', speed: 'kmh' }

/**
 * Names of the MILE and the KILOMETRE, per language. See the file docstring for
 * why an odometer idiom is deliberately not in here.
 */
const DISTANCE_UNIT_NAMES: Record<string, RegExp> = {
  en: /\b(miles?|kilometres?|kilometers?|km|mi)\b/iu,
  de: /\b(meilen?|kilometern?|km|mi)\b/iu,
  fr: /\b(milles?|miles?|kilom[eè]tres?|km|mi)\b/iu,
  pl: /\b(mila|mile|mil|kilometr|kilometry|kilometrów|km|mi)\b/iu,
  'pt-BR': /\b(milhas?|quil[oô]metros?|km|mi)\b/iu,
  ru: /(мил[яеиь]|километр|\bкм\b)/iu,
  uk: /(мил[яеіь]|кілометр|\bкм\b)/iu,
}

/**
 * The key the mileage-interval guard reports, PARSED from the component.
 *
 * Transcribing it would let a rename move this assertion onto a key nobody
 * renders. A shape this regex cannot read is a hard error, for the same reason
 * `unitDescriptionLocales.test.ts` refuses rather than skipping: the assertion
 * below would otherwise be checking nothing.
 */
function missingIntervalKey(): string {
  const source = readFileSync(resolve(__dirname, '../ReminderForm.tsx'), 'utf-8')
  const matches = [
    ...source.matchAll(/!mileageInterval\)\s*\{\s*setError\(t\('([^']+)'\)\)/g),
  ]
  if (matches.length !== 1) {
    throw new Error(
      `expected exactly one missing-interval setError in ReminderForm.tsx, found ${matches.length}`
    )
  }
  return matches[0][1]
}

const BASE_PROPS = { vin: 'V1', onClose: vi.fn(), onSuccess: vi.fn() }
const labelText = (id: string): string =>
  document.querySelector(`label[for="${id}"]`)?.textContent ?? ''
const field = (id: string): HTMLInputElement => document.getElementById(id) as HTMLInputElement

/** 80467 km is exactly 50000 mi. */
const CURRENT_KM = 80467
const MILEAGE_REMINDER = {
  id: 3,
  title: 'Service',
  reminder_type: 'mileage',
  due_mileage_km: 160935,
  notes: '',
} as unknown as Reminder

/** `Field` renders "<label> *" then " (<unit>)"; the prose is what precedes both. */
function proseOf(label: string): string {
  return label
    .replace(/\s*\([^()]*\)\s*$/u, '')
    .replace(/\s*\*\s*$/u, '')
    .trim()
}

beforeEach(() => {
  vi.clearAllMocks()
  langMock.code = 'en'
  unitPrefMock.units = METRIC_UNITS
})

describe('the resolving harness resolves, and covers every shipped language', () => {
  it('covers every code in SUPPORTED_LANGUAGES', () => {
    // A language added without a pattern would SKIP every case below while the
    // file still read as covering all of them, which is the shape this
    // workstream keeps finding: an inventory that is a floor.
    expect(SUPPORTED_LANGUAGES.map((l) => l.code).sort()).toEqual(
      Object.keys(DISTANCE_UNIT_NAMES).sort()
    )
  })

  it('renders real prose rather than keys', () => {
    // The receipt. If the bundles failed to load, `t` returns the key, every
    // assertion below passes vacuously (a key like `milesUntilDue` carries no
    // word boundary after "miles"), and this file would read as covering a
    // defect it could no longer see.
    langMock.code = 'en'
    unitPrefMock.units = METRIC_UNITS
    render(<ReminderForm {...BASE_PROPS} />)
    expect(labelText('reminder-title')).not.toContain('common:title')
    expect(labelText('reminder-title')).toContain('Title')
  })
})

describe.each(SUPPORTED_LANGUAGES.map((l) => l.code))(
  'ReminderForm mileage copy, resolved in %s',
  (lang) => {
    it.each([
      ['mi', LITRES_MILES],
      ['km', GALLONS_KM],
    ])('names no distance unit in its prose, and %s only in the suffix', async (label, units) => {
      langMock.code = lang
      unitPrefMock.units = units
      render(
        <ReminderForm {...BASE_PROPS} reminder={MILEAGE_REMINDER} currentMileage={CURRENT_KM} />
      )
      await waitFor(() => expect(field('reminder-mileage')).not.toBeNull())

      const rendered = labelText('reminder-mileage')
      expect(rendered).toContain(`(${label})`)
      expect(proseOf(rendered)).not.toMatch(DISTANCE_UNIT_NAMES[lang])
    })

    it('names no distance unit in the missing-interval message either', () => {
      const message = lookup(lang, 'forms', missingIntervalKey())
      expect(message, `${lang} has no string for ${missingIntervalKey()}`).toBeDefined()
      expect(message).not.toMatch(DISTANCE_UNIT_NAMES[lang])
    })
  }
)
