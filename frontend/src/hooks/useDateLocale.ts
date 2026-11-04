/**
 * Returns the locale string for date formatting, derived from the current i18n language
 * and this person's date format (see languageToDateLocale).
 *
 * The date format is the one useDateFormatSync publishes, not read from the account
 * here, so this works outside AuthProvider too. A change re-renders through
 * `useTranslation`: the sync announces it as `languageChanged`.
 */
import { useTranslation } from 'react-i18next'
import { getActiveDateFormat, languageToDateLocale } from '../constants/i18n'

export function useDateLocale(): string {
  const { i18n } = useTranslation()
  return languageToDateLocale(i18n.language, getActiveDateFormat())
}
