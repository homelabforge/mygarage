/**
 * Returns the locale string for date formatting, derived from the current i18n language.
 */
import { useTranslation } from 'react-i18next'
import { languageToLocale } from '../constants/i18n'

export function useDateLocale(): string {
  const { i18n } = useTranslation()
  return languageToLocale(i18n.language)
}
