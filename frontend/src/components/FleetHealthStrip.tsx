import { useTranslation } from 'react-i18next'
import { AlertTriangle, Calendar } from 'lucide-react'
import type { FleetHealth } from '../types/dashboard'
import { useCurrencyPreference } from '../hooks/useCurrencyPreference'
import { useUnitFormat } from '../hooks/useUnitFormat'
import { formatDateForDisplay } from '../utils/dateUtils'
import { Mono } from './ui'

interface FleetHealthStripProps {
  fleet: FleetHealth
}

/**
 * Fleet-health strip: one hairline-separated row of four cells
 * (Overdue / Upcoming-30d / Spent-{year} / Next-due). Bespoke by design —
 * `Tile` requires an icon and a single-line caption, which cells 3-4 don't
 * fit (G4 surface a). Tokenized: fixed-status danger/warning, neutral text
 * tokens, `--radius-panel` clip, `gap-px` over `--color-hair`. The Next-due
 * cell shows the reminder label plus its due date and/or its unit-formatted
 * due mileage (whichever the reminder carries — review finding 9).
 */
export default function FleetHealthStrip({ fleet }: FleetHealthStripProps) {
  const { t } = useTranslation('vehicles')
  const { formatCurrency } = useCurrencyPreference()
  const u = useUnitFormat()

  const nextDueWhen = fleet.next_due?.due_date
    ? formatDateForDisplay(fleet.next_due.due_date, {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
      })
    : null
  // due_mileage_km is canonical km (metric-canonical storage); rendered through
  // the resolved `units.distance` token, exactly like the card's odometer row.
  // `formatPrimary`, not `format`: this cell is one line of a four-cell strip
  // and a parenthesised counterpart would not fit it.
  const nextDueMileage = fleet.next_due?.due_mileage_km
    ? u.distance.formatPrimary(parseFloat(fleet.next_due.due_mileage_km))
    : null

  return (
    <div className="mb-6 grid grid-cols-1 gap-px overflow-hidden rounded-panel border border-border bg-hair sm:[grid-template-columns:repeat(auto-fit,minmax(200px,1fr))]">
      {/* Overdue */}
      <div className="flex items-center gap-[13px] bg-surface px-[18px] py-[15px]">
        <div className="flex h-[38px] w-[38px] shrink-0 items-center justify-center rounded-control bg-danger/15 text-danger">
          <AlertTriangle aria-hidden="true" className="h-[19px] w-[19px]" />
        </div>
        <div>
          <Mono size="2xl" weight="semibold" tone="danger">
            {fleet.overdue_count}
          </Mono>
          <div className="mt-1 text-[11.5px] text-text-mute">{t('dashboard.fleet.overdueCaption')}</div>
        </div>
      </div>

      {/* Upcoming — next 30 days */}
      <div className="flex items-center gap-[13px] bg-surface px-[18px] py-[15px]">
        <div className="flex h-[38px] w-[38px] shrink-0 items-center justify-center rounded-control bg-warning/15 text-warning">
          <Calendar aria-hidden="true" className="h-[19px] w-[19px]" />
        </div>
        <div>
          <Mono size="2xl" weight="semibold" tone="warning">
            {fleet.upcoming_30d_count}
          </Mono>
          <div className="mt-1 text-[11.5px] text-text-mute">{t('dashboard.fleet.upcomingCaption')}</div>
        </div>
      </div>

      {/* Spent this year — caption word + the year as adjacent data */}
      <div className="bg-surface px-[18px] py-[15px]">
        <div className="text-[11px] font-semibold uppercase tracking-[.06em] text-text-faint">
          {t('dashboard.fleet.spentLabel')} {fleet.year}
        </div>
        <Mono size="xl" weight="semibold" className="mt-2 block">
          {formatCurrency(fleet.spent_this_year, { zeroIsValid: true })}
        </Mono>
      </div>

      {/* Next due — label + due date and/or due mileage */}
      <div className="bg-surface px-[18px] py-[15px]">
        <div className="text-[11px] font-semibold uppercase tracking-[.06em] text-text-faint">
          {t('dashboard.fleet.nextDueLabel')}
        </div>
        {fleet.next_due ? (
          <>
            <div className="mt-2 text-sm font-semibold text-text">{fleet.next_due.label}</div>
            {nextDueWhen ? (
              <Mono size="sm" tone="warning" className="mt-0.5 block">
                {nextDueWhen}
              </Mono>
            ) : null}
            {nextDueMileage ? (
              <Mono size="sm" tone="muted" className="mt-0.5 block">
                {nextDueMileage}
              </Mono>
            ) : null}
          </>
        ) : (
          <div className="mt-2 text-sm text-text-mute">{t('dashboard.fleet.nextDueNone')}</div>
        )}
      </div>
    </div>
  )
}
