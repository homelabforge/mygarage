import type { ReactNode } from 'react'
import type { IconType, Tone } from './types'
import Mono from './Mono'

interface TileProps {
  /** A component type, not a rendered element — Tile owns the icon's size.
   *  IconType because this renders aria-hidden="true" (see Task 3). */
  icon: IconType
  /** Already translated by the caller. */
  label: string
  /** Number, currency string, or date — anything. Rendered in Mono. */
  value: ReactNode
  tone?: Tone
}

/**
 * A metric tile: icon, mono figure, caption.
 *
 * Extracted from `StatBadge` (VehicleStatisticsCard), which the same visual
 * pattern duplicates ~40 more times across Analytics, Calendar and Settings.
 * `count: number` became `value: ReactNode` because the KPI tiles show
 * currency and the Calendar tiles show dates.
 */
export default function Tile({ icon: Icon, label, value, tone = 'default' }: TileProps) {
  return (
    <div className="min-w-0 rounded-tile bg-surface-2 px-2.5 py-[15px] text-center">
      <Icon aria-hidden="true" className="mx-auto mb-2 h-4 w-4 text-text-mute" />
      <Mono size="xl" weight="semibold" tone={tone}>
        {value}
      </Mono>
      <div className="mt-1 max-w-full text-[10.5px] font-semibold uppercase leading-tight tracking-[.025em] text-text-faint [overflow-wrap:anywhere]">
        {label}
      </div>
    </div>
  )
}
