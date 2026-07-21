import type { ReactNode } from 'react'
import type { IconType } from './types'
import Mono from './Mono'

interface ListRowProps {
  /** A component type, not a rendered element. IconType because this renders
   *  aria-hidden="true" (see Task 3). */
  icon?: IconType
  /** Already translated by the caller. */
  label: string
  value: ReactNode
  /** Prototype carries this per-row (dc.html:3441). Values are mono, names
   *  and categories are not. */
  mono?: boolean
  onClick?: () => void
  trailing?: ReactNode
}

/**
 * A key → value row. Extracted from `ActivityRow` (VehicleStatisticsCard).
 *
 * data-testid is deliberate: shipped markup currently has zero test ids,
 * which leaves later phases selector-blind on list-heavy screens.
 */
export default function ListRow({
  icon: Icon,
  label,
  value,
  mono = true,
  onClick,
  trailing,
}: ListRowProps) {
  const body = (
    <>
      <span className="flex items-center gap-2 text-sm text-text-mute">
        {Icon ? <Icon aria-hidden="true" className="h-4 w-4" /> : null}
        {label}
      </span>
      <span className="flex items-center gap-2">
        {mono ? <Mono>{value}</Mono> : <span className="text-sm text-text">{value}</span>}
        {trailing}
      </span>
    </>
  )

  const classes = 'flex w-full items-center justify-between gap-3 py-2'

  if (onClick) {
    return (
      <button
        type="button"
        data-testid="list-row"
        onClick={onClick}
        className={`${classes} ui-focus-ring ui-motion ui-hover-surface rounded-row px-2 text-left`}
      >
        {body}
      </button>
    )
  }

  return (
    <div data-testid="list-row" className={classes}>
      {body}
    </div>
  )
}
