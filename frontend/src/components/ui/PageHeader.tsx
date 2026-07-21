import type { ReactNode } from 'react'

interface PageHeaderProps {
  /** Already translated by the caller. */
  title: string
  subtitle?: string
  actions?: ReactNode
}

/**
 * Page title block with a right-aligned action cluster.
 *
 * The type scale here is the design's, not the codebase's: clamp(22px,3vw,32px)
 * at weight 800 with -.02em tracking (prototype §Typography), replacing the
 * current `text-3xl font-bold` across ~19 sites.
 */
export default function PageHeader({ title, subtitle, actions }: PageHeaderProps) {
  return (
    <div className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <h1 className="text-[clamp(22px,3vw,32px)] font-extrabold tracking-[-.02em] text-text">
          {title}
        </h1>
        {subtitle ? <p className="mt-1 text-text-mute">{subtitle}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-3">{actions}</div> : null}
    </div>
  )
}
