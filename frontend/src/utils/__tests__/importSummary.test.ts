import { describe, expect, it } from 'vitest'
import i18next, { type TFunction } from 'i18next'
import vehiclesEn from '../../locales/en/vehicles.json'
import { buildImportSummary, type ImportSectionResult } from '../importSummary'

// Echoes the key, plus the count when one is passed, so a count that never
// reaches its line still fails.
const t = ((key: string, options?: { count?: number }): string =>
  options?.count === undefined ? key : `${key}=${options.count}`) as unknown as TFunction

// The shipped English bundle through a real i18next instance, bound to
// 'common' like the app's default, so a key that isn't namespace-qualified
// can't resolve by accident.
const english = async (): Promise<TFunction> => {
  const instance = i18next.createInstance()
  await instance.init({
    lng: 'en',
    ns: ['common', 'vehicles'],
    defaultNS: 'common',
    resources: { en: { common: {}, vehicles: vehiclesEn } },
    interpolation: { escapeValue: false },
  })
  return instance.t
}

const bucket = (success: number, skipped = 0, errors = 0): ImportSectionResult => ({
  success_count: success,
  skipped_count: skipped,
  error_count: errors,
})

const FIVE_SECTIONS = {
  service_records: bucket(2, 1),
  fuel_records: bucket(3, 0, 1),
  odometer_records: bucket(0),
  reminders: bucket(1),
  notes: bucket(4),
}

describe('buildImportSummary', () => {
  it('lists DEF, hours and insurance when the result carries them', () => {
    const summary = buildImportSummary(
      {
        ...FIVE_SECTIONS,
        def_records: bucket(5),
        hours_records: bucket(6, 2),
        insurance_policies: bucket(1, 0, 1),
      },
      t,
    )
    const lines = summary.split('\n')
    expect(lines.find((l) => l.includes('defList.title'))).toBe(
      'vehicles:defList.title: ✓ vehicles:detail.misc.importedCount=5',
    )
    expect(lines.find((l) => l.includes('hoursList.title'))).toBe(
      'vehicles:hoursList.title: ✓ vehicles:detail.misc.importedCount=6, ○ vehicles:detail.misc.skippedCount=2',
    )
    expect(lines.find((l) => l.includes('insuranceList.title'))).toBe(
      'vehicles:insuranceList.title: ✓ vehicles:detail.misc.importedCount=1, ✗ vehicles:detail.misc.errorCount=1',
    )
  })

  it('leaves the three out when the result has no bucket for them', () => {
    const summary = buildImportSummary(FIVE_SECTIONS, t)
    expect(summary).not.toContain('defList.title')
    expect(summary).not.toContain('hoursList.title')
    expect(summary).not.toContain('insuranceList.title')
  })

  it('renders the five existing sections in English exactly as before', async () => {
    expect(buildImportSummary(FIVE_SECTIONS, await english())).toBe(
      'Import completed:\n' +
        '\nService Records: ✓ 2 imported, ○ 1 skipped' +
        '\nFuel Records: ✓ 3 imported, ✗ 1 error(s)' +
        '\nOdometer Records: ✓ 0 imported' +
        '\nMaintenance (from reminders): ✓ 1 imported' +
        '\nNotes: ✓ 4 imported',
    )
  })

  it('lists every section in the order the backend imports them', async () => {
    const summary = buildImportSummary(
      {
        ...FIVE_SECTIONS,
        def_records: bucket(5),
        hours_records: bucket(6, 2),
        insurance_policies: bucket(1, 0, 1),
      },
      await english(),
    )
    expect(summary).toBe(
      'Import completed:\n' +
        '\nService Records: ✓ 2 imported, ○ 1 skipped' +
        '\nFuel Records: ✓ 3 imported, ✗ 1 error(s)' +
        '\nDEF Records: ✓ 5 imported' +
        '\nOdometer Records: ✓ 0 imported' +
        '\nEngine Hours Readings: ✓ 6 imported, ○ 2 skipped' +
        '\nMaintenance (from reminders): ✓ 1 imported' +
        '\nNotes: ✓ 4 imported' +
        '\nInsurance Policies: ✓ 1 imported, ✗ 1 error(s)',
    )
  })
})

describe('buildImportSummary: the errors and warnings behind the counts (J2, N-3)', () => {
  const SEVEN_ERRORS = ['e1', 'e2', 'e3', 'e4', 'e5', 'e6', 'e7']

  it('lists the first five errors, how many more there are, then the warnings', () => {
    const summary = buildImportSummary(
      { ...FIVE_SECTIONS, errors: SEVEN_ERRORS, warnings: ['w1'] },
      t,
    )
    // main: the counts only, so neither list is in the toast
    expect(summary.endsWith(
      '\n\nvehicles:detail.misc.importErrorsHeading' +
        '\ne1\ne2\ne3\ne4\ne5' +
        '\nvehicles:detail.misc.importMoreCount=2' +
        '\n\nvehicles:detail.misc.importWarningsHeading' +
        '\nw1',
    )).toBe(true)
  })

  it('renders the lists and the new sections in English', async () => {
    expect(
      buildImportSummary(
        {
          service_records: bucket(1),
          financing_records: bucket(2),
          tax_records: bucket(1),
          toll_tags: bucket(1),
          toll_transactions: bucket(3, 1),
          warranties: bucket(1),
          spot_rentals: bucket(0, 0, 1),
          errors: SEVEN_ERRORS,
          warnings: ['Toll transaction 0: its toll tag was not imported, saved without one'],
        },
        await english(),
      ),
    ).toBe(
      'Import completed:\n' +
        '\nService Records: ✓ 1 imported' +
        '\nFinancing: ✓ 2 imported' +
        '\nTax & Registration Records: ✓ 1 imported' +
        '\nToll Tags: ✓ 1 imported' +
        '\nToll Transactions: ✓ 3 imported, ○ 1 skipped' +
        '\nWarranties: ✓ 1 imported' +
        '\nSpot Rentals: ✓ 0 imported, ✗ 1 error(s)' +
        '\n\nErrors:\ne1\ne2\ne3\ne4\ne5\n+2 more' +
        '\n\nWarnings:\nToll transaction 0: its toll tag was not imported, saved without one',
    )
  })
})
