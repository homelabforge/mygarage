import type { ReactElement } from 'react'
import type { Tone } from './types'

export type ProgressMeterTone = Extract<Tone, 'accent' | 'warning' | 'danger' | 'muted'>

interface ProgressMeterProps {
  /** Already translated by the caller. Names the bar for assistive tech. */
  label: string
  /** 0-100. Values outside the range are clamped, so a caller can pass a raw
   *  share times 100: a reminder a quarter past due is 125. */
  percent: number
  /** Status tones are fixed (design §4.9); `accent` follows the user's accent. */
  tone?: ProgressMeterTone
  /** What the bar means in words ("1,240 mi left"), announced in place of the
   *  bare percentage. */
  valueText?: string
  className?: string
}

const FILL: Record<ProgressMeterTone, string> = {
  accent: 'bg-(--accent-solid)',
  warning: 'bg-warning',
  danger: 'bg-danger',
  muted: 'bg-text-mute',
}

/**
 * A bare progress bar: how far along something is, in a status colour.
 *
 * Not ShareBar, which is a legend row with its own label, figures and a raw
 * chart colour. This one carries no text: the caller sets the words beside it,
 * and they reach assistive tech through `valueText`. role="progressbar", like
 * ShareBar and Stepper, because aria-valuenow/min/max are range-widget
 * attributes AT ignores on a group.
 */
export default function ProgressMeter({
  label,
  percent,
  tone = 'accent',
  valueText,
  className = '',
}: ProgressMeterProps): ReactElement {
  const clamped = Math.round(Math.max(0, Math.min(100, percent)))
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuenow={clamped}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuetext={valueText}
      className={`h-1.5 w-full overflow-hidden rounded-pill bg-surface-2 ${className}`}
    >
      <div className={`h-full rounded-pill ${FILL[tone]}`} style={{ width: `${clamped}%` }} />
    </div>
  )
}
