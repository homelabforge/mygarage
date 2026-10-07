/**
 * Whether this person's vehicles get their periodic technical inspection
 * reminder scheduled automatically from the country profile (#211). On by
 * default; off hands those reminders back to the person (the engine pauses
 * its rule and dismisses the reminder it made, and never touches a rule a
 * person made). Saves to the account, or to this browser when sign-in is
 * off, like the other Quick Settings preferences.
 */

import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { usePersonalPreference } from '@/hooks/usePersonalPreference'
import { useSavePersonalPreference } from '@/hooks/useSavePersonalPreference'
import Toggle from '../ui/Toggle'

/** Where the preference lives in this browser when there is no account. */
export const INSPECTION_AUTO_SCHEDULE_STORAGE_KEY = 'inspection_auto_schedule'

/** 'false' is the only value that turns it off: unset means the default, on. */
export function asAutoSchedule(value: string | null | undefined): boolean {
  return value !== 'false'
}

export function useInspectionAutoSchedule(): boolean {
  return usePersonalPreference(
    'inspection_auto_schedule',
    INSPECTION_AUTO_SCHEDULE_STORAGE_KEY,
    asAutoSchedule
  )
}

export default function InspectionAutoScheduleControl(): React.ReactElement {
  const { t } = useTranslation('settings')
  const stored = useInspectionAutoSchedule()
  const save = useSavePersonalPreference()
  // The new state shows at once; a failed save puts the stored one back.
  const [saved, setSaved] = useState<boolean | null>(null)
  const [saving, setSaving] = useState(false)
  const enabled = saved ?? stored

  const choose = async (next: boolean): Promise<void> => {
    setSaving(true)
    setSaved(next)
    try {
      await save('inspection_auto_schedule', String(next), INSPECTION_AUTO_SCHEDULE_STORAGE_KEY)
      toast.success(t('inspection.saved'))
    } catch {
      toast.error(t('inspection.error'))
      setSaved(null)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div>
      <p className="ui-eyebrow mb-2">{t('inspection.label')}</p>
      <Toggle
        id="quick-settings-inspection-auto-schedule"
        label={t('inspection.autoSchedule')}
        checked={enabled}
        onChange={(next) => void choose(next)}
        disabled={saving}
      />
      <p className="mt-1 text-xs text-garage-text-muted">{t('inspection.description')}</p>
    </div>
  )
}
