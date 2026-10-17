import type { ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import { History } from 'lucide-react'
import { toast } from 'sonner'

import { useDeleteBrakeJob, useDeleteBrakeMeasurement } from '../../hooks/queries/useBrakes'
import { useUnitFormat } from '../../hooks/useUnitFormat'
import type { BrakeCorner, BrakeJob, BrakeMeasurement, BrakeOverview } from '../../types/brake'
import { formatDateForDisplay } from '../../utils/dateUtils'
import { formatHours } from '../../utils/hoursFormat'
import { getActionErrorMessage } from '../../utils/httpErrorHandler'
import { Badge, Button, Drawer, EmptyState } from '../ui'
import { formatMm, num, useBrakeText } from './useBrakeText'

interface BrakeHistoryDrawerProps {
  vin: string
  overview: BrakeOverview
  corner: BrakeCorner | null
  open: boolean
  onClose: () => void
  onEditMeasurement: (measurement: BrakeMeasurement) => void
  onEditJob: (job: BrakeJob) => void
}

type Row =
  | { kind: 'measurement'; day: string; id: number; measurement: BrakeMeasurement }
  | { kind: 'job'; day: string; id: number; job: BrakeJob }

/**
 * One corner's brake jobs and measurements, newest first. Edit opens a nested
 * drawer; delete asks with a native confirm, since a modal opened from a
 * drawer is inert in this app.
 */
export default function BrakeHistoryDrawer({
  vin,
  overview,
  corner,
  open,
  onClose,
  onEditMeasurement,
  onEditJob,
}: BrakeHistoryDrawerProps): ReactElement {
  const { t } = useTranslation('vehicles')
  const u = useUnitFormat()
  const text = useBrakeText()
  const removeMeasurement = useDeleteBrakeMeasurement(vin)
  const removeJob = useDeleteBrakeJob(vin)

  /* Newest first, so within one day the new pads the job wrote come first,
     then the job, then the old pads: the reverse of the order the work
     happened in, and of how the wear estimate reads them (a same-day
     measurement the job didn't write is the old part). */
  const rank = (row: Row): number =>
    row.kind === 'job' ? 1 : row.measurement.brake_job_id != null ? 2 : 0
  const rows: Row[] = [
    ...(corner?.jobs ?? []).map((job): Row => ({ kind: 'job', day: job.performed_on, id: job.id, job })),
    ...(corner?.measurements ?? []).map(
      (measurement): Row => ({ kind: 'measurement', day: measurement.recorded_at, id: measurement.id, measurement })
    ),
  ].sort((a, b) => {
    if (a.day !== b.day) return a.day < b.day ? 1 : -1
    if (rank(a) !== rank(b)) return rank(b) - rank(a)
    return b.id - a.id
  })

  const reading = (odometer: number | string | null | undefined, hours: number | string | null | undefined): string => {
    const figures = [
      ...(overview.tracks_distance && odometer != null ? [u.distance.format(num(odometer))] : []),
      ...(overview.tracks_hours && hours != null ? [formatHours(hours)] : []),
    ]
    return figures.length > 0 ? ` @ ${figures.join(' · ')}` : ''
  }

  const figures = (m: BrakeMeasurement): string => {
    const parts: string[] = []
    if (m.inner_pad_mm != null) parts.push(t('brakes.figureInner', { value: formatMm(m.inner_pad_mm) }))
    if (m.outer_pad_mm != null) parts.push(t('brakes.figureOuter', { value: formatMm(m.outer_pad_mm) }))
    if (m.shoe_mm != null) parts.push(t('brakes.figureShoe', { value: formatMm(m.shoe_mm) }))
    if (m.rotor_mm != null) parts.push(t('brakes.figureRotor', { value: formatMm(m.rotor_mm) }))
    if (m.drum_mm != null) parts.push(t('brakes.figureDrum', { value: formatMm(m.drum_mm) }))
    return parts.join(' · ')
  }

  const work = (job: BrakeJob): string => {
    const drum = job.brake_type === 'drum'
    const parts: string[] = []
    if (job.friction_replaced) parts.push(drum ? t('brakes.shoesReplaced') : t('brakes.padsReplaced'))
    if (job.surface === 'replaced') parts.push(drum ? t('brakes.drumReplaced') : t('brakes.rotorReplaced'))
    if (job.surface === 'resurfaced') parts.push(drum ? t('brakes.drumResurfaced') : t('brakes.rotorResurfaced'))
    return parts.join(' · ')
  }

  const deleteMeasurement = (m: BrakeMeasurement): void => {
    if (!confirm(t('brakes.confirmDeleteMeasurement', { date: formatDateForDisplay(m.recorded_at) }))) return
    removeMeasurement.mutate(m.id, {
      onSuccess: () => toast.success(t('brakes.measurementDeleted')),
      onError: (err: unknown) => toast.error(getActionErrorMessage(err, t('brakes.deleteAction'))),
    })
  }

  const deleteJob = (job: BrakeJob): void => {
    if (!confirm(t('brakes.confirmDeleteJob', { date: formatDateForDisplay(job.performed_on) }))) return
    removeJob.mutate(job.id, {
      onSuccess: () => toast.success(t('brakes.jobDeleted')),
      onError: (err: unknown) => toast.error(getActionErrorMessage(err, t('brakes.deleteAction'))),
    })
  }

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={t('brakes.historyTitle', { position: corner ? text.labelFor(corner.position) : '' })}
      icon={History}
      width="sm"
      closeLabel={t('common:close')}
    >
      {rows.length === 0 ? (
        <EmptyState icon={History} title={t('brakes.historyEmpty')} description={t('brakes.historyEmptyHint')} />
      ) : (
        <ul className="space-y-2">
          {rows.map((row) =>
            row.kind === 'job' ? (
              <li key={`job-${row.id}`} className="space-y-1 rounded-card border border-border p-3">
                <div className="flex items-start justify-between gap-2">
                  <div className="flex flex-wrap items-center gap-2 font-semibold">
                    {t('brakes.brakeJob')}
                    <Badge tone="info">{text.typeLabel(row.job.brake_type)}</Badge>
                  </div>
                  <div className="flex gap-1">
                    <Button size="sm" variant="ghost" onClick={() => onEditJob(row.job)}>
                      {t('brakes.edit')}
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => deleteJob(row.job)}>
                      {t('common:delete')}
                    </Button>
                  </div>
                </div>
                <div className="font-mono text-xs">
                  {formatDateForDisplay(row.job.performed_on)}
                  {reading(row.job.odometer_km, row.job.engine_hours)}
                </div>
                <div className="text-sm">{work(row.job)}</div>
                {row.job.notes && <div className="text-sm text-text-mute">{row.job.notes}</div>}
              </li>
            ) : (
              <li key={`m-${row.id}`} className="space-y-1 rounded-card border border-border p-3">
                <div className="flex items-start justify-between gap-2">
                  <div className="flex flex-wrap items-center gap-2 font-semibold">
                    {t('brakes.measurement')}
                    {row.measurement.brake_job_id != null && <Badge tone="muted">{t('brakes.newPartsBadge')}</Badge>}
                  </div>
                  <div className="flex gap-1">
                    <Button size="sm" variant="ghost" onClick={() => onEditMeasurement(row.measurement)}>
                      {t('brakes.edit')}
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => deleteMeasurement(row.measurement)}>
                      {t('common:delete')}
                    </Button>
                  </div>
                </div>
                <div className="font-mono text-xs">
                  {formatDateForDisplay(row.measurement.recorded_at)}
                  {reading(row.measurement.odometer_km, row.measurement.engine_hours)}
                </div>
                <div className="font-mono text-xs">{figures(row.measurement)}</div>
                {row.measurement.notes && <div className="text-sm text-text-mute">{row.measurement.notes}</div>}
              </li>
            )
          )}
        </ul>
      )}
    </Drawer>
  )
}
