import type { ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import { AlertTriangle } from 'lucide-react'

import ClickableCard from '../ClickableCard'
import { Button, Chip, ProgressMeter, type ProgressMeterTone } from '../ui'
import type { BrakeAxle, BrakeCorner, BrakeOverview } from '../../types/brake'
import { formatDateForDisplay } from '../../utils/dateUtils'
import { num } from '../../utils/wireNumber'
import { formatMm, useBrakeText } from './useBrakeText'

interface BrakeCornerCardProps {
  corner: BrakeCorner
  axle: BrakeAxle
  overview: BrakeOverview
  onLog: () => void
  onJob: () => void
  onHistory: () => void
}

/** A pad's tone: at or below the minimum, inside the due-soon band, or fine. */
function meterTone(value: number, axle: BrakeAxle): ProgressMeterTone {
  if (value <= Number(axle.min_thickness_mm)) return 'danger'
  if (value <= Number(axle.due_soon_mm)) return 'warning'
  return 'accent'
}

/**
 * One corner's brakes: condition, pads against new and minimum, the rotor or
 * drum, the wear estimate and when it was last measured. The whole card opens
 * the corner's history; its buttons keep their own clicks.
 */
export default function BrakeCornerCard({
  corner,
  axle,
  overview,
  onLog,
  onJob,
  onHistory,
}: BrakeCornerCardProps): ReactElement {
  const { t } = useTranslation('vehicles')
  const text = useBrakeText()
  const chip = text.chip(corner)
  const drum = corner.brake_type === 'drum'
  const full = Number(axle.new_thickness_mm)

  /* `on` is when that pad was last measured. A one-pad check keeps the other
     pad's last figure, which can be older than the corner's last measurement. */
  const pads: { label: string; value: number | null; on: string | null | undefined }[] = drum
    ? [{ label: t('brakes.shoe'), value: num(corner.shoe_mm), on: corner.measured_on }]
    : [
        { label: t('brakes.innerPad'), value: num(corner.inner_pad_mm), on: corner.inner_pad_measured_on },
        { label: t('brakes.outerPad'), value: num(corner.outer_pad_mm), on: corner.outer_pad_measured_on },
      ]
  const measuredPads = pads.filter(
    (pad): pad is { label: string; value: number; on: string | null | undefined } => pad.value !== null
  )
  const carried = measuredPads.filter((pad) => pad.on && corner.measured_on && pad.on !== corner.measured_on)

  const limit = drum ? axle.drum_max_mm : axle.rotor_min_mm
  const surface =
    corner.surface_mm == null
      ? '—'
      : limit != null
        ? drum
          ? t('brakes.drumWithMax', { value: formatMm(corner.surface_mm), max: formatMm(limit) })
          : t('brakes.rotorWithMin', { value: formatMm(corner.surface_mm), min: formatMm(limit) })
        : formatMm(corner.surface_mm)

  return (
    <ClickableCard
      padding="sm"
      className="space-y-3"
      label={t('brakes.historyOpen', { position: text.labelFor(corner.position) })}
      onActivate={onHistory}
    >
      <div className="space-y-0.5">
        <div className="flex flex-wrap items-center gap-2 font-semibold">
          {text.labelFor(corner.position)}
          <Chip tone={chip.tone}>{chip.label}</Chip>
        </div>
        <div className="text-sm text-text-mute">
          {drum
            ? t('brakes.drumLimits', {
                new: formatMm(axle.new_thickness_mm),
                min: formatMm(axle.min_thickness_mm),
              })
            : t('brakes.discLimits', {
                new: formatMm(axle.new_thickness_mm),
                min: formatMm(axle.min_thickness_mm),
              })}
        </div>
      </div>

      {measuredPads.length > 0 && (
        <div className="space-y-2">
          {measuredPads.map((pad) => (
            <div key={pad.label} className="grid grid-cols-[5.5rem_1fr_4rem] items-center gap-2 text-sm">
              <span className="text-text-mute">{pad.label}</span>
              <ProgressMeter
                label={pad.label}
                percent={full > 0 ? (pad.value / full) * 100 : 0}
                tone={meterTone(pad.value, axle)}
                valueText={formatMm(pad.value)}
              />
              <span className="text-right font-mono text-xs">{formatMm(pad.value)}</span>
            </div>
          ))}
          {carried.map((pad) => (
            <p key={pad.label} className="text-xs text-text-mute">
              {t('brakes.carriedPad', { pad: pad.label, date: formatDateForDisplay(pad.on ?? '') })}
            </p>
          ))}
        </div>
      )}

      <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-sm">
        <dt className="text-text-mute">{drum ? t('brakes.drum') : t('brakes.rotor')}</dt>
        <dd className="flex items-center gap-1 font-mono text-xs">
          {surface}
          {corner.surface_past_limit && (
            <span className="inline-flex items-center gap-1 font-sans text-danger">
              <AlertTriangle aria-hidden="true" className="h-3.5 w-3.5" />
              {t('brakes.pastLimit')}
            </span>
          )}
        </dd>
        <dt className="text-text-mute">{t('brakes.wearEstimate')}</dt>
        <dd className="font-mono text-xs">{text.wearSummary(corner, overview)}</dd>
        <dt className="text-text-mute">{t('brakes.lastMeasured')}</dt>
        <dd className="font-mono text-xs">{text.measuredLine(corner, overview)}</dd>
      </dl>

      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="secondary" onClick={onLog}>
          {t('brakes.logMeasurement')}
        </Button>
        <Button size="sm" variant="ghost" onClick={onJob}>
          {t('brakes.brakeJob')}
        </Button>
        <Button size="sm" variant="ghost" onClick={onHistory}>
          {t('brakes.history')}
        </Button>
      </div>
    </ClickableCard>
  )
}
