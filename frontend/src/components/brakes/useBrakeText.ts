import { useTranslation } from 'react-i18next'

import { getActiveLocale } from '../../constants/i18n'
import { useUnitFormat } from '../../hooks/useUnitFormat'
import { formatDateForDisplay } from '../../utils/dateUtils'
import { formatHours } from '../../utils/hoursFormat'
import type { BrakeCorner, BrakeOverview, BrakePosition, BrakeType } from '../../types/brake'
import type { Tone } from '../ui'

/** API decimals arrive as strings; the formatters take numbers. */
export const num = (v: number | string | null | undefined): number | null =>
  v === null || v === undefined || v === '' ? null : Number(v)

/**
 * A brake figure in millimetres. Brakes are millimetres only for now (#202):
 * pad gauges and the MIN TH stamped on a rotor read in mm.
 */
export function formatMm(value: number | string): string {
  const shown = new Intl.NumberFormat(getActiveLocale(), {
    minimumFractionDigits: 1,
    maximumFractionDigits: 2,
  }).format(Number(value))
  return `${shown} mm`
}

export interface BrakeText {
  /** "Front Left" and so on, from the tire screen's own corner names. */
  labelFor: (position: BrakePosition) => string
  /** "Disc" / "Drum". */
  typeLabel: (type: BrakeType) => string
  /** The chip a corner shows, with its tone. */
  chip: (corner: BrakeCorner) => { label: string; tone: Tone }
  /** What the wear estimate line says, for every status. */
  wearSummary: (corner: BrakeCorner, overview: BrakeOverview) => string
  /** "Sep 4, 2026 @ 46,050 mi", or the date alone when no reading came with it. */
  measuredLine: (corner: BrakeCorner, overview: BrakeOverview) => string
}

/**
 * The words the brake screens share.
 *
 * Every key is a literal t() call: validate-i18n-usage only sees literal keys,
 * and a computed one would ship a raw key on a typo.
 */
export function useBrakeText(): BrakeText {
  const { t } = useTranslation('vehicles')
  const u = useUnitFormat()

  const positionLabels: Record<BrakePosition, string> = {
    FL: t('tireList.positions.FL'),
    FR: t('tireList.positions.FR'),
    RL: t('tireList.positions.RL'),
    RR: t('tireList.positions.RR'),
  }

  const usageText = (overview: BrakeOverview, value: number | string): string =>
    overview.usage_axis === 'hours' ? formatHours(value) : u.distance.format(num(value))

  return {
    labelFor: (position) => positionLabels[position],
    typeLabel: (type) => (type === 'drum' ? t('brakes.drum') : t('brakes.disc')),
    chip: (corner) => {
      switch (corner.condition) {
        case 'replace_now':
          return { label: t('brakes.condition.replaceNow'), tone: 'danger' }
        case 'due_soon':
          return { label: t('brakes.condition.dueSoon'), tone: 'warning' }
        case 'unknown':
          return { label: t('brakes.condition.unknown'), tone: 'muted' }
        default:
          return corner.wear_status === 'insufficient_measurements'
            ? { label: t('brakes.condition.oneMeasurement'), tone: 'info' }
            : { label: t('brakes.condition.ok'), tone: 'success' }
      }
    },
    wearSummary: (corner, overview) => {
      const hours = overview.usage_axis === 'hours'
      switch (corner.wear_status) {
        case 'projected': {
          if (corner.projected_usage_remaining == null) return '—'
          const left = `~${usageText(overview, corner.projected_usage_remaining)}`
          return corner.projected_wear_date
            ? `${left} · ${formatDateForDisplay(corner.projected_wear_date)}`
            : left
        }
        case 'at_or_below_minimum':
          return t('brakes.wear.replaceNow')
        case 'replaced_not_measured':
          return corner.brake_type === 'drum' ? t('brakes.wear.newShoes') : t('brakes.wear.newPads')
        case 'insufficient_measurements':
          return t('brakes.wear.needsSecond')
        case 'no_usage_figures':
          return hours ? t('brakes.wear.needsHours') : t('brakes.wear.needsOdometer')
        case 'no_usage_between':
          return hours ? t('brakes.wear.needsLaterHours') : t('brakes.wear.needsLaterOdometer')
        case 'not_decreasing':
          return t('brakes.wear.notDecreasing')
        default:
          return t('brakes.wear.notMeasured')
      }
    },
    measuredLine: (corner, overview) => {
      if (!corner.measured_on) return '—'
      const date = formatDateForDisplay(corner.measured_on)
      const reading =
        overview.usage_axis === 'hours' ? corner.measured_hours : corner.measured_odometer_km
      return reading != null ? `${date} @ ${usageText(overview, reading)}` : date
    },
  }
}
