/**
 * Publishes this person's date format to the non-React date formatters
 * (formatDateForDisplay, formatDateTime and the `getActiveDateLocale()`
 * callers), which cannot read a hook.
 *
 * Those formatters run during render and nothing re-renders them when the
 * module-level value changes, so a change is announced the way a language
 * change is: every component that uses `useTranslation` re-renders on
 * `languageChanged`. The language itself is unchanged.
 */
import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { setActiveDateFormat } from '../constants/i18n'
import { useDateFormat } from './useDateFormat'

export function useDateFormatSync(): void {
  const { i18n } = useTranslation()
  const { dateFormat } = useDateFormat()

  useEffect(() => {
    if (setActiveDateFormat(dateFormat)) {
      i18n.emit('languageChanged', i18n.language)
    }
  }, [dateFormat, i18n])
}
