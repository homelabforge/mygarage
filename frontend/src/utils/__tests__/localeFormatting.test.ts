import { describe, it, expect, afterEach } from 'vitest'
import { getActiveLocale, setActiveLocale } from '@/constants/i18n'
import { makeUnitFormat } from '@/utils/unitFormat'
import { presetUnitsFor } from '@/types/units'
import { formatDateForDisplay, getDateFnsLocale } from '@/utils/dateUtils'

/**
 * Number formatting must follow the language the user picked in the app.
 *
 * A bare `toLocaleString()` follows the BROWSER locale instead, so a German
 * user could still get English separators (and an English user German ones)
 * depending on their browser rather than their setting. UnitFormatter is a
 * static class outside React and cannot call useDateLocale(), so it reads the
 * active locale that src/i18n.ts keeps in sync on languageChanged.
 */
describe('locale-aware number formatting', () => {
  afterEach(() => setActiveLocale('en'))

  it('maps a language to its Intl locale', () => {
    setActiveLocale('de')
    expect(getActiveLocale()).toBe('de-DE')
    setActiveLocale('pl')
    expect(getActiveLocale()).toBe('pl-PL')
  })

  it('falls back to en-US for an unknown language', () => {
    setActiveLocale('xx')
    expect(getActiveLocale()).toBe('en-US')
  })

  it('formats distance with the separators of the active language', () => {
    // Through the resolved `km` adapter: task 6 deleted the binary
    // `formatDistance`, and the grouping this case is about is the same
    // `Intl.NumberFormat(getActiveLocale())` either way.
    const km = makeUnitFormat(presetUnitsFor('metric', 'us')).distance
    setActiveLocale('en')
    const en = km.format(12345)
    setActiveLocale('de')
    const de = km.format(12345)

    // en-US groups with a comma, de-DE with a period — the point is that the
    // two differ, which is exactly what a bare toLocaleString() failed to do.
    expect(en).toBe('12,345 km')
    expect(de).toBe('12.345 km')
    expect(en).not.toBe(de)
  })

  it('formats mass with the separators of the active language', () => {
    // Was `UnitFormatter.formatWeight(1500, 'metric')`, a binary method that
    // plan 3b task 2 deleted because no production file called it. The
    // resolved-set formatter reads the same active locale, and the assertion
    // gets stronger on the way across: the original only claimed the two
    // strings differ, which a change of unit would also satisfy.
    const mass = makeUnitFormat(presetUnitsFor('metric', 'us')).mass
    setActiveLocale('en')
    const en = mass.format(1500)
    setActiveLocale('de')
    const de = mass.format(1500)

    expect(en).toBe('1,500.00 kg')
    expect(de).toBe('1.500,00 kg')
    expect(en).not.toBe(de)
  })

  it('formats dates in the active language by default', () => {
    // The default used to be a hardcoded 'en-US', and 26 of 34 call sites omit
    // the argument — so most dates in the UI ignored the chosen language.
    setActiveLocale('en')
    const en = formatDateForDisplay('2026-08-14')
    setActiveLocale('de')
    const de = formatDateForDisplay('2026-08-14')

    expect(en).toContain('Aug')
    expect(en).not.toBe(de)
  })

  it('still honours an explicitly passed locale', () => {
    setActiveLocale('de')
    expect(formatDateForDisplay('2026-08-14', undefined, 'en-US')).toContain('Aug')
  })

  it('maps the active language to a date-fns locale object', () => {
    // date-fns needs a locale OBJECT, not the Intl string, which is why
    // relative times ("3 months ago") stayed English everywhere.
    setActiveLocale('de')
    expect(getDateFnsLocale().code).toBe('de')
    setActiveLocale('en')
    expect(getDateFnsLocale().code).toBe('en-US')
  })
})
