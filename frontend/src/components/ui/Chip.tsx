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
      className={`${base} ui-focus-ring ui-motion ui-hover-line cursor-pointer`}
    >
      {content}
    </button>
  )
}
