import type { ReactNode } from 'react'

interface PageContainerProps {
  children: ReactNode
  className?: string
}

/**
 * The page measure: 1320px max with fluid gutters (prototype §Global Shell).
 *
 * Deliberately NOT Tailwind's `container`, which steps at breakpoints and
 * yields a different width from the design at every viewport. This is a real
 * layout change, not a cosmetic one — every page migrated in P4-P11 inherits
 * its measure from here.
 */
export default function PageContainer({ children, className = '' }: PageContainerProps) {
  return (
    <div className={`mx-auto max-w-[1320px] px-[clamp(16px,3vw,30px)] py-8 ${className}`}>
      {children}
    </div>
  )
}
