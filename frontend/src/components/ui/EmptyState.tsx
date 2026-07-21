import type { ReactNode } from 'react'
import type { IconType } from './types'

interface EmptyStateProps {
  /** IconType, not an inline ComponentType: this renders the icon with
   *  aria-hidden="true", a string literal that a `boolean`-typed prop
   *  rejects (TS2769). See Task 3. */
  icon: IconType
  title: string
  description?: string
  action?: ReactNode
  /** `md` for a full-card empty state, `sm` inside a table body. */
  size?: 'sm' | 'md'
}

/**
 * Centred icon + heading + one-line description + a single CTA.
 *
 * Replaces 38 hand-rolled copies across 23 files. Two padding conventions
 * exist in the codebase today — py-16 inside cards, py-8 inside tables —
 * which is what `size` encodes.
 */
export default function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  size = 'md',
}: EmptyStateProps) {
  return (
    <div className={`text-center ${size === 'md' ? 'py-16' : 'py-8'}`}>
      <Icon
        aria-hidden="true"
        className={`mx-auto mb-4 opacity-50 text-text-mute ${size === 'md' ? 'h-16 w-16' : 'h-10 w-10'}`}
      />
      <h3 className={`font-semibold text-text ${size === 'md' ? 'text-xl' : 'text-base'}`}>
        {title}
      </h3>
      {description ? <p className="mt-2 text-text-mute">{description}</p> : null}
      {action ? <div className="mt-6 flex justify-center">{action}</div> : null}
    </div>
  )
}
