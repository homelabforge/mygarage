/**
 * 12-hour or 24-hour times, for this person. Lives in Quick Settings.
 */

import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { useSavePersonalPreference } from '@/hooks/useSavePersonalPreference'
import { useTimeFormat, type TimeFormat } from '@/hooks/useTimeFormat'
import { segmentClass } from './choiceStyles'

export default function TimeFormatControl(): React.ReactElement {
  const { t } = useTranslation('settings')
  const { timeFormat: stored } = useTimeFormat()
  const save = useSavePersonalPreference()
  // Shows the choice until the save settles.
  const [pending, setPending] = useState<TimeFormat | null>(null)
  const [saving, setSaving] = useState(false)
  const timeFormat = pending ?? stored

  const choose = async (format: TimeFormat): Promise<void> => {
    setSaving(true)
    setPending(format)
    try {
      await save('time_format', format, 'time_format')
      toast.success(t('preferences.timeSaved'))
    } catch {
      toast.error(t('preferences.timeError'))
    } finally {
      // Once the save settles the stored value wins, so a later change elsewhere shows.
      setPending(null)
      setSaving(false)
    }
  }

  const segment = (value: TimeFormat, label: string): React.ReactElement => (
    <button
      type="button"
      aria-pressed={timeFormat === value}
      disabled={saving}
      onClick={() => void choose(value)}
      className={segmentClass(timeFormat === value, saving)}
    >
      {label}
    </button>
  )

  return (
    <div>
      <span className="ui-eyebrow mb-2 block">{t('timeFormat.label')}</span>
      <div role="group" aria-label={t('timeFormat.label')} className="flex gap-2">
        {segment('12h', t('timeFormat.twelveHour'))}
        {segment('24h', t('timeFormat.twentyFourHour'))}
      </div>
    </div>
  )
}
