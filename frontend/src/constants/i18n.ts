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
]

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
