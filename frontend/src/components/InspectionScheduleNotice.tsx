/**
 * The one thing the automatic inspection engine (#211) needs and cannot
 * find on its own: the vehicle's first registration date. Shown on the
 * Reminders tab while the vehicle's country has a periodic inspection and
 * the date is blank; nothing otherwise. The date is entered in the Basic
 * information card.
 */

import { useTranslation } from 'react-i18next'
import { CalendarClock } from 'lucide-react'
import { useCountryProfile } from '@/hooks/queries/useCountryProfile'
import { useResolvedCountry } from '@/hooks/useResolvedCountry'
import type { Vehicle } from '@/types/vehicle'
import { Card } from './ui'

interface InspectionScheduleNoticeProps {
  vehicle: Vehicle | null | undefined
}

export default function InspectionScheduleNotice({ vehicle }: InspectionScheduleNoticeProps) {
  const { t } = useTranslation('vehicles')
  const country = useResolvedCountry(vehicle)
  const { data: profile } = useCountryProfile(country)
  const name = profile?.inspection?.name
  if (!vehicle || !name || vehicle.first_registration_date || vehicle.archived_at) return null
  return (
    <Card padding="sm" className="mb-4">
      <div role="note" className="flex items-start gap-3">
        <CalendarClock aria-hidden="true" className="mt-0.5 h-5 w-5 shrink-0 text-(--accent-fg)" />
        <p className="text-sm text-text">{t('reminderList.inspectionNeedsDate', { name })}</p>
      </div>
    </Card>
  )
}
