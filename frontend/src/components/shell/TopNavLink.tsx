import { NavLink } from 'react-router-dom'

interface TopNavLinkProps {
  to: string
  /** Already translated by the caller (t(item.labelKey)). */
  label: string
  variant?: 'inline' | 'stacked'
  /** Hamburger rows call this to close the panel on navigation. */
  onNavigate?: () => void
}

const INLINE = {
  base: 'relative cursor-pointer whitespace-nowrap px-[13px] py-2 text-sm transition-colors',
  active: 'font-semibold text-text',
  inactive: 'font-medium text-text-mute hover:text-text',
}

const STACKED = {
  base: 'flex cursor-pointer items-center rounded-icon px-3 py-[11px] text-[14.5px] transition-colors',
  active: 'font-semibold text-text bg-(--accent-soft)',
  inactive: 'font-medium text-text-mute hover:text-text',
}

/**
 * One nav link. Inline (top bar) gets the accent-underline active treatment
 * (prototype dc.html:47-56); stacked (hamburger panel) gets an accent-soft
 * active row (dc.html:112-123). Active state comes from react-router NavLink's
 * isActive — `end` on '/' so Dashboard is not active on every route. The
 * underline is aria-hidden so the accessible name stays the label alone (§4.8).
 */
export default function TopNavLink({ to, label, variant = 'inline', onNavigate }: TopNavLinkProps) {
  const s = variant === 'stacked' ? STACKED : INLINE
  return (
    <NavLink
      to={to}
      end={to === '/'}
      onClick={onNavigate}
      className={({ isActive }) => `${s.base} ${isActive ? s.active : s.inactive}`}
    >
      {({ isActive }) => (
        <>
          {label}
          {variant === 'inline' && isActive ? (
            <span
              aria-hidden="true"
              className="absolute right-[13px] bottom-[-1px] left-[13px] h-0.5 rounded-[2px] bg-(--accent)"
            />
          ) : null}
        </>
      )}
    </NavLink>
  )
}
