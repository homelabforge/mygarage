import type { ReactNode } from 'react'

interface CardProps {
  children: ReactNode
  padding?: 'none' | 'sm' | 'md'
  /** Hover lift + accent border. Requires onClick; renders a <button>. */
  interactive?: boolean
  onClick?: () => void
  /** For masonry/column layouts that must not split a card. */
  breakInside?: boolean
  className?: string
}

const PADDING = {
  none: '',
  sm: 'p-4',
  md: 'p-6',
} as const

/**
 * The layered surface. Replaces the most-repeated string in the codebase —
 * `bg-garage-surface rounded-lg border border-garage-border p-6` appears 21
 * times verbatim and ~108 times with variations.
 *
 * An interactive card is a real <button>, not a div with onClick: the whole
 * vehicle card is clickable per the design, and that has to be reachable by
 * keyboard.
 */
export default function Card({
  children,
  padding = 'md',
  interactive = false,
  onClick,
  breakInside = false,
  className = '',
}: CardProps) {
  const classes = [
    'rounded-card border border-border bg-surface',
    PADDING[padding],
    breakInside ? 'break-inside-avoid' : '',
    interactive ? 'ui-motion ui-hover-line ui-focus-ring hover:shadow-card-hover w-full text-left cursor-pointer' : '',
    className,
  ]
    .filter(Boolean)
    .join(' ')

  if (interactive) {
    return (
      <button type="button" onClick={onClick} className={classes}>
        {children}
      </button>
    )
  }

  return <div className={classes}>{children}</div>
}
