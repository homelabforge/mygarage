import type { ReactNode } from 'react'
import type { IconType } from './types'

interface CardHeaderProps {
  /** Already translated by the caller. */
  title: string
  /** IconType: this renders aria-hidden="true", which a boolean-typed prop
   *  rejects (TS2769). See Task 3. */
  icon?: IconType
  actions?: ReactNode
  /** Muted line under the title. Already translated by the caller. */
  description?: string
  /** 'trailing' (default) parks the icon right of the actions; 'leading' puts
   *  it before the title, the Settings > Integrations look. */
  iconPosition?: 'trailing' | 'leading'
}

/**
 * Title row inside a Card. Replaces ~40 hand-rolled
 * `flex items-center justify-between mb-2` + h3 blocks.
 */
export default function CardHeader({
  title,
  icon: Icon,
  actions,
  description,
  iconPosition = 'trailing',
}: CardHeaderProps): React.ReactElement {
  const heading = <h3 className="text-[15px] font-bold tracking-[-.02em] text-text">{title}</h3>
  const desc = description ? <p className="mt-0.5 text-sm text-text-mute">{description}</p> : null

  if (iconPosition === 'leading') {
    return (
      <header className="mb-4 flex items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          {Icon ? <Icon aria-hidden="true" className="mt-0.5 h-5 w-5 shrink-0 text-(--accent-fg)" /> : null}
          <div>
            {heading}
            {desc}
          </div>
        </div>
        {actions}
      </header>
    )
  }

  // No description keeps the bare h3 and items-center, so the existing callers'
  // markup doesn't move. With one, top-align like every other described header.
  return (
    <div className={`mb-3 flex ${desc ? 'items-start' : 'items-center'} justify-between gap-3`}>
      {desc ? (
        <div>
          {heading}
          {desc}
        </div>
      ) : (
        heading
      )}
      <div className="flex items-center gap-2">
        {actions}
        {Icon ? (
          <Icon aria-hidden="true" className={desc ? 'mt-0.5 h-5 w-5 text-(--accent-fg)' : 'h-5 w-5 text-(--accent-fg)'} />
        ) : null}
      </div>
    </div>
  )
}
