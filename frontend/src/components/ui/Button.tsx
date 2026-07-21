import type { ButtonHTMLAttributes } from 'react'
import { Loader2 } from 'lucide-react'
import type { IconType, Size } from './types'

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'accentTint'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: Size
  /** IconType, not an inline ComponentType: both icons render with
   *  aria-hidden="true", which a boolean-typed prop rejects (see Task 3). */
  icon?: IconType
  iconRight?: IconType
  /** Disables the button and swaps the leading icon for a spinner. The label
   *  stays rendered so the accessible name does not change mid-flight. */
  loading?: boolean
}

const HEIGHT: Record<Size, string> = {
  sm: 'h-btn-sm px-3 text-xs',
  md: 'h-btn-md px-4 text-sm',
  lg: 'h-btn-lg px-5 text-sm',
}

/**
 * `text-(--accent-on-solid)` on the solid variant is load-bearing, not a
 * flourish: `text-white` on amber is ~2:1 contrast. Each accent ships its own
 * readable foreground (design §4.3) precisely so a solid accent button is
 * legible for all six.
 *
 * Hover treatments are §4.8's, not improvised: solid gets the color-mix lift
 * (ui-hover-solid), bordered variants move the border to --accent-line
 * (ui-hover-line) rather than swapping their fill, and only ghost — which has
 * neither a border nor a fill — tints its surface.
 */
const VARIANT: Record<ButtonVariant, string> = {
  primary: 'bg-(--accent-solid) text-(--accent-on-solid) ui-hover-solid hover:shadow-accent font-semibold',
  secondary: 'bg-surface-2 text-text border border-border ui-hover-line',
  ghost: 'bg-transparent text-text-mid ui-hover-surface',
  danger: 'bg-danger/15 text-danger border border-danger/40 hover:bg-danger/25',
  accentTint: 'bg-(--accent-soft) text-(--accent-fg) border border-(--accent-line) ui-hover-line',
}

export default function Button({
  variant = 'primary',
  size = 'md',
  icon: Icon,
  iconRight: IconRight,
  loading = false,
  disabled,
  type = 'button',
  className = '',
  children,
  ...rest
}: ButtonProps) {
  const LeadingIcon = loading ? Loader2 : Icon

  return (
    <button
      // Defaults to "button". A bare <button> inside a <form> submits it, and
      // this library will be dropped into 14 forms whose tests submit via
      // container.querySelector('form').
      type={type}
      disabled={disabled || loading}
      className={[
        'ui-focus-ring ui-motion ui-disabled cursor-pointer inline-flex items-center justify-center gap-2 rounded-control whitespace-nowrap',
        HEIGHT[size],
        VARIANT[variant],
        className,
      ]
        .filter(Boolean)
        .join(' ')}
      {...rest}
    >
      {LeadingIcon ? (
        <LeadingIcon
          aria-hidden="true"
          className={`h-4 w-4 shrink-0 ${loading ? 'animate-spin' : ''}`}
        />
      ) : null}
      {children}
      {IconRight && !loading ? (
        <IconRight aria-hidden="true" className="h-4 w-4 shrink-0" />
      ) : null}
    </button>
  )
}
