import type { ReactNode } from 'react'
import type { IconType, Tone } from './types'
import Mono from './Mono'

interface BadgeProps {
  children?: ReactNode
  /** Numeric badges render in Mono — prototype dc.html:74, 80. */
  count?: number
  tone?: Tone
  icon?: IconType
  className?: string
}

/**
 * Status fills are fixed colours (design §4.9), so their foreground is fixed
 * too — one token, not text-white/text-black. White on --color-danger is
 * 3.55:1, below AA; --color-on-status measures 5.9:1 there and ≥10:1 on the
 * other three fills.
 */
const TONE: Record<Tone, string> = {
  default: 'bg-badge-bg text-badge-tx',
  muted: 'bg-surface-3 text-text-mute',
  accent: 'bg-(--accent-soft) text-(--accent-fg)',
  success: 'bg-success text-on-status',
  warning: 'bg-warning text-on-status',
  danger: 'bg-danger text-on-status',
  info: 'bg-info text-on-status',
}

/**
 * A status marker attached to something else — the overdue count on a
 * vehicle card, the unread count on the nav bell.
 *
 * Distinct from Chip: a Badge reports state and is not interactive; a Chip
 * labels a category and often is.
 */
export default function Badge({
  children,
  count,
  tone = 'default',
  icon: Icon,
  className = '',
}: BadgeProps) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-chip px-2 py-1 text-xs font-semibold ${TONE[tone]} ${className}`}
    >
      {Icon ? <Icon aria-hidden="true" className="h-3.5 w-3.5" /> : null}
      {count !== undefined ? (
        // inherit: the span above already sets this tone's own foreground
        // (text-badge-tx / text-text-mute / --accent-fg / text-on-status) —
        // Mono's own default ('text-text') would override it, same defect
        // just fixed in Stepper (d212dd9).
        <Mono size="xs" weight="semibold" tone="inherit">{count}</Mono>
      ) : (
        children
      )}
    </span>
  )
}
