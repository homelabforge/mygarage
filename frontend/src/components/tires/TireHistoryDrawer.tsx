import { Gauge } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'

import { useDeleteTireReading } from '../../hooks/queries/useTires'
import { useUnitFormat } from '../../hooks/useUnitFormat'
import type {
  HistoryFault,
  MountedPosition,
  Tire,
  TireMountPeriod,
  TirePosition,
  TireReading,
  UsageAxis,
} from '../../types/tire'
import { formatDateForDisplay } from '../../utils/dateUtils'
import { formatHours } from '../../utils/hoursFormat'
import { getActionErrorMessage } from '../../utils/httpErrorHandler'
import { Badge, Button, Drawer, EmptyState, ListRow } from '../ui'

interface TireHistoryDrawerProps {
  vin: string
  tire: Tire | null
  open: boolean
  onClose: () => void
  onEditPeriod: (period: TireMountPeriod) => void
  /** Opens the reading editor for this row's reading. */
  onEditReading: (reading: TireReading) => void
  onAddPeriod: () => void
  /** The card's position label, passed in so the five t() calls stay in one place. */
  labelFor: (position: TirePosition) => string
  /** Whether the vehicle takes an odometer. Defaults to true, as before #217. */
  tracksDistance?: boolean
  /** Whether the vehicle takes an hour meter (#217). */
  tracksHours?: boolean
}

/**
 * Whether a blocking period is blocked by a MISSING bound.
 *
 * The wire says which periods block a figure, not why. But a period that is
 * fully bounded and still blocks can only be a fault (reversed, overlapping,
 * contradicting a reading), so the kind is derivable from the period's own
 * fields, and the two badges below are worded for the two repairs: supply a
 * number, or correct one.
 */
export function needsOdometer(period: TireMountPeriod): boolean {
  if (period.mounted_odometer_km == null) return true
  return period.dismounted_on != null && period.dismounted_odometer_km == null
}

/** Whether a period lacks the bound its tire's figures run on (#217). */
export function needsReading(period: TireMountPeriod, axis: UsageAxis): boolean {
  if (axis !== 'hours') return needsOdometer(period)
  if (period.mounted_hours == null) return true
  return period.dismounted_on != null && period.dismounted_hours == null
}

/**
 * Whether the card should offer Fix: a figure is blocked, or the history holds
 * a contradiction that would refuse edits. The second is the case the card
 * could not see before v3.4.0: a period no figure depends on can still refuse
 * every write that touches it.
 */
export function needsFix(tire: Tire): boolean {
  return (tire.blocking_period_ids?.length ?? 0) > 0 || (tire.history_faults?.length ?? 0) > 0
}

/**
 * A tire's history: its mount periods first, then its readings.
 *
 * Rebuilt out of `TireList.tsx` for v3.4.0, when the mount-period section and
 * the editor arrived. The response already carried `mount_periods`,
 * `installed_date` and `blocking_period_ids` since v3.3.0 and nothing read
 * them; this is the first surface that does.
 */
export default function TireHistoryDrawer({
  vin,
  tire,
  open,
  onClose,
  onEditPeriod,
  onEditReading,
  onAddPeriod,
  labelFor,
  tracksDistance = true,
  tracksHours = false,
}: TireHistoryDrawerProps) {
  const { t } = useTranslation('vehicles')
  const u = useUnitFormat()
  const removeReading = useDeleteTireReading(vin)
  const num = (v: number | string | null | undefined): number | null =>
    v === null || v === undefined || v === '' ? null : Number(v)

  /* `mount_periods` arrives oldest first: TireService sorts by (mounted_on,
     id) before building the response, and `installed_date` is derived from
     [0]. Re-sorting here would be a second, drifting source of truth. */
  const periods: TireMountPeriod[] = tire?.mount_periods ?? []
  /* `readings` arrives newest-first, likewise. */
  const readings: TireReading[] = tire?.readings ?? []
  const blocking = new Set(tire?.blocking_period_ids ?? [])
  /* Each contradiction is shown on BOTH of its periods: an overlap is as much
     the earlier period's problem as the later one's, and the repair may be on
     either side. */
  const faultsByPeriod = new Map<number, HistoryFault[]>()
  for (const fault of tire?.history_faults ?? []) {
    for (const id of [fault.period_id, fault.counterpart_id]) {
      if (id == null) continue
      faultsByPeriod.set(id, [...(faultsByPeriod.get(id) ?? []), fault])
    }
  }
  const first = periods[0]

  const axis: UsageAxis = tire?.usage_axis ?? 'distance'
  const odometer = (v: number | string | null | undefined): string =>
    v != null ? u.distance.format(num(v)) : t('tireList.odometerUnknown')
  const hoursText = (v: number | string | null | undefined): string =>
    v != null ? formatHours(v) : t('tireList.hoursUnknown')
  const day = (v: string | null | undefined): string =>
    v ? formatDateForDisplay(v) : t('tireList.dateUnknown')
  const bound = (
    d: string | null | undefined,
    o: number | string | null | undefined,
    h: number | string | null | undefined
  ): string => {
    const figures = [...(tracksDistance ? [odometer(o)] : []), ...(tracksHours ? [hoursText(h)] : [])]
    return `${day(d)} @ ${figures.join(' · ')}`
  }
  /* A period with a figure on the other axis only: the vehicle switched, or one was left out. */
  const missingAxis =
    axis === 'hours'
      ? periods.some((p) => p.mounted_odometer_km != null && p.mounted_hours == null)
      : periods.some((p) => p.mounted_hours != null && p.mounted_odometer_km == null)

  /* For a reading that shouldn't be there at all; a wrong value is fixed with
     Edit, which keeps the reading. A native confirm, since a modal opened from a
     drawer is inert in this app. */
  const deleteReading = (reading: TireReading): void => {
    if (!tire) return
    if (!confirm(t('tireList.readingConfirmDelete', { date: formatDateForDisplay(reading.recorded_at) }))) {
      return
    }
    removeReading.mutate(
      { tireId: tire.id, readingId: reading.id },
      {
        onSuccess: () => toast.success(t('tireList.readingDeleted')),
        onError: (err: unknown) =>
          toast.error(getActionErrorMessage(err, t('tireList.readingDeleteAction'))),
      }
    )
  }

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={t('tireList.historyTitle', { position: tire ? labelFor(tire.position) : '' })}
      icon={Gauge}
      width="sm"
      closeLabel={t('common:close')}
    >
      {/* Always the Mount history section first, Add past period included: a
          tire never mounted in MyGarage (no periods, no readings) is the
          feature's main user, and a fully-empty special case here made the
          one control that could add either unreachable from a stored tire's
          unconditional History button. The periods list has its own "No
          mount history yet" text, and the readings section keeps its own
          inner empty state below. */}
      <div className="space-y-6">
        <section className="space-y-2">
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-sm font-semibold text-text-mute">{t('tireList.mountHistory')}</h3>
            <Button size="sm" variant="ghost" onClick={onAddPeriod}>
              {t('tireList.addPastPeriod')}
            </Button>
          </div>
          {missingAxis && (
            <p className="text-sm text-text-mute">
              {axis === 'hours' ? t('tireList.axisNeedsHours') : t('tireList.axisNeedsOdometer')}
            </p>
          )}
          <p className="text-sm">
            {tire?.installed_date && first
              ? t('tireList.firstInstalled', {
                  date: formatDateForDisplay(tire.installed_date),
                  odometer:
                    axis === 'hours' ? hoursText(first.mounted_hours) : odometer(first.mounted_odometer_km),
                })
              : t('tireList.firstInstalledUnknown')}
          </p>
          {periods.length === 0 ? (
            <p className="text-sm text-text-mute">{t('tireList.historyNoPeriods')}</p>
          ) : (
            <ul className="space-y-2">
              {periods.map((period) => {
                const flagged = blocking.has(period.id) || faultsByPeriod.has(period.id)
                return (
                  <li
                    key={period.id}
                    data-testid={`period-${period.id}`}
                    className="space-y-1 rounded-card border border-border p-3"
                  >
                    <div className="flex items-start justify-between gap-2">
                      {/* `MountPeriodResponse.position` is generated as plain `string`
                          (the backend schema has no Literal there), but a period is
                          always mounted at one of the five corners. */}
                      <div className="font-semibold">{labelFor(period.position as MountedPosition)}</div>
                      <Button size="sm" variant="ghost" onClick={() => onEditPeriod(period)}>
                        {t('tireList.periodEdit')}
                      </Button>
                    </div>
                    <div className="font-mono text-xs">
                      {period.dismounted_on == null
                        ? t('tireList.periodSince', {
                            from: bound(period.mounted_on, period.mounted_odometer_km, period.mounted_hours),
                          })
                        : t('tireList.periodRange', {
                            from: bound(period.mounted_on, period.mounted_odometer_km, period.mounted_hours),
                            to: bound(
                              period.dismounted_on,
                              period.dismounted_odometer_km,
                              period.dismounted_hours
                            ),
                          })}
                    </div>
                    {(period.is_assumed || flagged) && (
                      <div className="flex flex-wrap gap-2">
                        {period.is_assumed && <Badge tone="info">{t('tireList.periodAssumed')}</Badge>}
                        {flagged &&
                          (blocking.has(period.id) && needsReading(period, axis) ? (
                            <Badge tone="warning">
                              {axis === 'hours' ? t('tireList.periodNeedsHours') : t('tireList.periodNeedsOdometer')}
                            </Badge>
                          ) : (
                            <Badge tone="danger">{t('tireList.periodCheck')}</Badge>
                          ))}
                      </div>
                    )}
                    {faultsByPeriod.get(period.id)?.[0] ? (
                      <p data-testid={`period-${period.id}-fault`} className="text-sm text-text-mute">
                        {faultsByPeriod.get(period.id)?.[0]?.message}
                      </p>
                    ) : null}
                    {period.is_assumed && period.observed_active_on ? (
                      <p className="text-sm text-text-mute">
                        {t('tireList.periodAssumedHint', {
                          date: formatDateForDisplay(period.observed_active_on),
                        })}
                      </p>
                    ) : null}
                    {period.notes ? <p className="text-sm text-text-mute">{period.notes}</p> : null}
                  </li>
                )
              })}
            </ul>
          )}
        </section>

        <section className="space-y-2">
          <h3 className="text-sm font-semibold text-text-mute">{t('tireList.readingsHeading')}</h3>
          {/* `readings` arrives newest-first: TireService sorts descending by
              recorded_at before building the response, and the projection reads
              [0] and [1] as the two most recent. Re-sorting here would be a
              second, drifting source of truth for the same order. */}
          {readings.length > 0 ? (
            <ul className="space-y-2">
              {readings.map((reading: TireReading) => (
                <li
                  key={reading.id}
                  data-testid={`reading-${reading.id}`}
                  className="space-y-1 rounded-card border border-border p-3"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="font-semibold">{formatDateForDisplay(reading.recorded_at)}</div>
                    <div className="flex gap-1">
                      <Button
                        size="sm"
                        variant="ghost"
                        aria-label={t('tireList.readingEditLabel', {
                          date: formatDateForDisplay(reading.recorded_at),
                        })}
                        onClick={() => onEditReading(reading)}
                      >
                        {t('common:edit')}
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        aria-label={t('tireList.readingDeleteLabel', {
                          date: formatDateForDisplay(reading.recorded_at),
                        })}
                        disabled={removeReading.isPending}
                        onClick={() => deleteReading(reading)}
                      >
                        {t('common:delete')}
                      </Button>
                    </div>
                  </div>
                  {/* Every value through the same adapters the card uses, so a
                      history row can never disagree with the card above it. The
                      ternaries stay spelled out per row rather than folding into
                      a shared cell() helper: validate-units.ts matches lexical
                      expression shapes, and a helper that converts INTERNALLY is
                      exactly the form its manifest notes it cannot see. */}
                  <ListRow
                    label={t('tireList.tread')}
                    value={
                      reading.tread_depth_mm != null ? u.tread.format(num(reading.tread_depth_mm)) : '—'
                    }
                  />
                  <ListRow
                    label={t('tireList.pressure')}
                    value={
                      reading.pressure_kpa != null ? u.pressure.format(num(reading.pressure_kpa)) : '—'
                    }
                  />
                  {tracksDistance && (
                    <ListRow
                      label={t('tireList.odometer')}
                      value={
                        reading.odometer_km != null ? u.distance.format(num(reading.odometer_km)) : '—'
                      }
                    />
                  )}
                  {tracksHours && (
                    <ListRow
                      label={t('common:engineHours')}
                      value={reading.engine_hours != null ? formatHours(reading.engine_hours) : '—'}
                    />
                  )}
                  {reading.notes ? <p className="text-sm text-text-mute">{reading.notes}</p> : null}
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState
              icon={Gauge}
              size="sm"
              title={t('tireList.historyEmpty')}
              description={t('tireList.historyEmptyHint')}
            />
          )}
        </section>
      </div>
    </Drawer>
  )
}
