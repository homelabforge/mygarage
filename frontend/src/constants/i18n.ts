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
  { code: 'pl', name: 'Polish', nativeName: 'Polski' },
  { code: 'uk', name: 'Ukrainian', nativeName: 'Українська' },
  { code: 'ru', name: 'Russian', nativeName: 'Русский' },
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
    pl: 'pl-PL',
    uk: 'uk-UA',
    ru: 'ru-RU',
  }
  return map[lang] ?? 'en-US'
}
