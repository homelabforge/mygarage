/**
 * Returns the locale string for everything that isn't a date: numbers, money,
 * quantities and country names. It follows the language only.
 *
 * Use useDateLocale for dates. An English user who picks day-first gets en-GB
 * dates, and en-GB numbers or country names would leak in here (`US$5.00`,
 * `St Helena`) if this read the date locale.
 */
import { useTranslation } from 'react-i18next'
import { languageToLocale } from '../constants/i18n'

export function useLanguageLocale(): string {
  const { i18n } = useTranslation()
  return languageToLocale(i18n.language)
}
