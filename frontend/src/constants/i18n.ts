/**
 * Internationalization constants — frontend mirror of backend allowlists.
 * Adding a language/currency = update both this file and backend/app/constants/i18n.py.
 */

export interface SupportedLanguage {
  code: string
  name: string
  nativeName: string
}

export interface SupportedCurrency {
  code: string
  name: string
}

export const SUPPORTED_LANGUAGES: SupportedLanguage[] = [
  { code: 'en', name: 'English', nativeName: 'English' },
  { code: 'fr', name: 'French', nativeName: 'Français' },
  { code: 'pl', name: 'Polish', nativeName: 'Polski' },
  { code: 'uk', name: 'Ukrainian', nativeName: 'Українська' },
  { code: 'ru', name: 'Russian', nativeName: 'Русский' },
  { code: 'pt-BR', name: 'Brazilian Portuguese', nativeName: 'Português (Brasil)' },
  { code: 'de', name: 'German', nativeName: 'Deutsch' },
  { code: 'ms', name: 'Malay', nativeName: 'Bahasa Melayu' },
  { code: 'it', name: 'Italian', nativeName: 'Italiano' },
]

export const SUPPORTED_CURRENCIES: SupportedCurrency[] = [
  { code: 'USD', name: 'US Dollar' },
  { code: 'EUR', name: 'Euro' },
  { code: 'GBP', name: 'British Pound' },
  { code: 'PLN', name: 'Polish Zloty' },
  { code: 'UAH', name: 'Ukrainian Hryvnia' },
  { code: 'CAD', name: 'Canadian Dollar' },
  { code: 'AUD', name: 'Australian Dollar' },
  { code: 'JPY', name: 'Japanese Yen' },
  { code: 'CHF', name: 'Swiss Franc' },
  { code: 'SEK', name: 'Swedish Krona' },
  { code: 'NOK', name: 'Norwegian Krone' },
  { code: 'DKK', name: 'Danish Krone' },
  { code: 'CZK', name: 'Czech Koruna' },
  { code: 'HUF', name: 'Hungarian Forint' },
  { code: 'BRL', name: 'Brazilian Real' },
  { code: 'INR', name: 'Indian Rupee' },
  { code: 'MYR', name: 'Malaysian Ringgit' },
]

const SUPPORTED_CURRENCY_CODES: ReadonlySet<string> = new Set(SUPPORTED_CURRENCIES.map((c) => c.code))

/**
 * The code when the backend would accept it, else null.
 *
 * Exact match, same as the backend's validator. Intl throws on a malformed
 * code and two of the cost formatters don't catch it.
 */
export function supportedCurrencyCode(code: string | null | undefined): string | null {
  return code != null && SUPPORTED_CURRENCY_CODES.has(code) ? code : null
}

/** Map language code to locale for Intl.NumberFormat / Intl.DateTimeFormat */
export function languageToLocale(lang: string): string {
  const map: Record<string, string> = {
    en: 'en-US',
    fr: 'fr-FR',
    pl: 'pl-PL',
    uk: 'uk-UA',
    ru: 'ru-RU',
    'pt-BR': 'pt-BR',
    de: 'de-DE',
    ms: 'ms-MY',
    it: 'it-IT',
  }
  return map[lang] ?? 'en-US'
}

/**
 * The active Intl locale, kept in sync with the i18n language by src/i18n.ts.
 *
 * Non-React code (UnitFormatter and friends) cannot call useDateLocale(), and a
 * bare `toLocaleString()` follows the BROWSER locale, not the language the user
 * picked in the app — so a German user could still get English separators.
 * Reading it from here keeps number formatting tied to the chosen language.
 */
let activeLocale = 'en-US'

export function setActiveLocale(lang: string): void {
  activeLocale = languageToLocale(lang)
}

export function getActiveLocale(): string {
  return activeLocale
}

/**
 * The household time zone, published by `/settings/public` as
 * `effective_timezone` and stored here (same module-level pattern as
 * `activeLocale`) so non-React code like `formatDateForInput` can read it.
 * Null until the payload arrives; the browser zone applies until then.
 */
let householdTimeZone: string | null = null

export function setHouseholdTimeZone(zone: string | null): void {
  householdTimeZone = zone && zone.trim() !== '' ? zone : null
}

export function getHouseholdTimeZone(): string | null {
  return householdTimeZone
}

/**
 * Today's calendar date (YYYY-MM-DD) in the household zone.
 *
 * A date the browser fills in or compares against is a second "today", so it
 * must agree with the server's. Falls back to the browser zone until the
 * store is set, or if the published zone name is one this browser rejects.
 */
export function todayInHousehold(): string {
  const build = (timeZone?: string): string => {
    const parts = new Intl.DateTimeFormat('en-CA', {
      timeZone,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    }).formatToParts(new Date())
    const get = (type: string): string => parts.find((p) => p.type === type)?.value ?? ''
    return `${get('year')}-${get('month')}-${get('day')}`
  }
  if (householdTimeZone) {
    try {
      return build(householdTimeZone)
    } catch {
      // An invalid zone from the server must not break every form default.
    }
  }
  return build(undefined)
}
