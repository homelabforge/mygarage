/**
 * Day-first or month-first dates, for this person. Lives in Quick Settings.
 *
 * Only English has a choice to make: every other language the app speaks
 * writes dates day-first already, so the control is hidden for them.
 */

import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { languageToLocale } from '@/constants/i18n'
import { useSavePersonalPreference } from '@/hooks/useSavePersonalPreference'
import { useDateFormat, type DateFormat } from '@/hooks/useDateFormat'
import { segmentClass } from './choiceStyles'

export default function DateFormatControl(): React.ReactElement | null {
  const { t, i18n } = useTranslation('settings')
  const { dateFormat: stored } = useDateFormat()
  const save = useSavePersonalPreference()
  // Shows the choice before the save lands; dropped if the save fails.
  const [pending, setPending] = useState<DateFormat | null>(null)
  const [saving, setSaving] = useState(false)
  const dateFormat = pending ?? stored

  const choose = async (format: DateFormat): Promise<void> => {
    setSaving(true)
    setPending(format)
    try {
      await save('date_format', format, 'date_format')
      toast.success(t('preferences.dateSaved'))
    } catch {
      toast.error(t('preferences.dateError'))
      setPending(null)
    } finally {
      setSaving(false)
    }
  }

  const segment = (value: DateFormat, label: string): React.ReactElement => (
    <button
      type="button"
      aria-pressed={dateFormat === value}
      disabled={saving}
      onClick={() => void choose(value)}
      className={segmentClass(dateFormat === value, saving)}
    >
      {label}
    </button>
  )

  if (languageToLocale(i18n.language) !== 'en-US') return null

  return (
    <div>
      <span className="ui-eyebrow mb-2 block">{t('dateFormat.label')}</span>
      <div role="group" aria-label={t('dateFormat.label')} className="flex gap-2">
        {segment('mdy', t('dateFormat.monthFirst'))}
        {segment('dmy', t('dateFormat.dayFirst'))}
      </div>
    </div>
  )
}
