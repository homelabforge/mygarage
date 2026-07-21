import type { ReactNode } from 'react'
import type { IconType } from './types'

interface CardHeaderProps {
  /** Already translated by the caller. */
  title: string
  /** IconType — this renders aria-hidden="true", which a boolean-typed prop
   *  rejects (TS2769). See Task 3. */
  icon?: IconType
  actions?: ReactNode
}

/**
 * Title row inside a Card. Replaces ~40 hand-rolled
 * `flex items-center justify-between mb-2` + h3 blocks.
 */
export default function CardHeader({ title, icon: Icon, actions }: CardHeaderProps) {
  return (
    <div className="mb-3 flex items-center justify-between gap-3">
      <h3 className="text-[15px] font-bold tracking-[-.02em] text-text">{title}</h3>
      <div className="flex items-center gap-2">
        {actions}
        {Icon ? <Icon aria-hidden="true" className="h-5 w-5 text-(--accent-fg)" /> : null}
      </div>
    </div>
  )
}
