import type { ReactNode } from 'react'
import type { IconType, Tone } from './types'

interface ChipProps {
  children: ReactNode
  tone?: Tone
  icon?: IconType
  /** Present ⇒ renders a real <button> with aria-pressed. */
  onClick?: () => void
  selected?: boolean
  className?: string
}

const TONE: Record<Tone, string> = {
  default: 'bg-surface-3 text-text-dim border-border',
  muted: 'bg-surface-3 text-text-mute border-border-soft',
  accent: 'bg-(--accent-soft) text-(--accent-fg) border-(--accent-line)',
  success: 'bg-success/15 text-success border-success/40',
  warning: 'bg-warning/15 text-warning border-warning/40',
  danger: 'bg-danger/15 text-danger border-danger/40',
  info: 'bg-info/15 text-info border-info/40',
}

/**
 * Interactive-only hover treatment, kept separate from TONE because it
 * diverges by tone family. `ui-hover-line` (index.css) hardcodes
 * border-color: var(--accent-line) — correct for default/muted/accent,
 * which are accent-following, but wrong for the fixed-status tones (design
 * §4.9: status colours never shift toward the user's accent). Those instead
 * bump the same-colour background on hover, matching Button's danger variant
 * (`hover:bg-danger/25`) rather than borrowing an accent-derived utility.
 */
const HOVER: Record<Tone, string> = {
  default: 'ui-hover-line',
  muted: 'ui-hover-line',
  accent: 'ui-hover-line',
  success: 'hover:bg-success/25',
  warning: 'hover:bg-warning/25',
  danger: 'hover:bg-danger/25',
  info: 'hover:bg-info/25',
}

/**
 * A categorical label or filter control — Car/Truck/RV on a vehicle card,
 * the Address Book category filters.
 *
 * Interactive chips are real buttons carrying aria-pressed, not divs with
 * click handlers: the filter bars are keyboard-reachable surfaces.
 */
export default function Chip({
  children,
  tone = 'default',
  icon: Icon,
  onClick,
  selected = false,
  className = '',
}: ChipProps) {
  const base = `inline-flex items-center gap-1.5 rounded-chip border px-2.5 py-1 text-xs font-medium ${TONE[selected ? 'accent' : tone]} ${className}`
  const content = (
    <>
      {Icon ? <Icon aria-hidden="true" className="h-3.5 w-3.5" /> : null}
      {children}
    </>
  )

  if (!onClick) {
    return <span className={base}>{content}</span>
  }

  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={selected}
      className={`${base} ui-focus-ring ui-motion ${HOVER[selected ? 'accent' : tone]} cursor-pointer`}
    >
      {content}
    </button>
  )
}
