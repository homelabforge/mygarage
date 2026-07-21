import type { ButtonHTMLAttributes } from 'react'
import type { IconType, Size } from './types'

type IconButtonVariant = 'surface' | 'ghost' | 'danger'

interface IconButtonProps
  extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'aria-label' | 'title'> {
  /** IconType — rendered with aria-hidden="true" (see Task 3). */
  icon: IconType
  /** Required. Becomes aria-label, and title unless `title` overrides it.
   *  Not optional on purpose: several existing bare-icon buttons ship with
   *  no accessible name at all. */
  label: string
  /** Tooltip text when it should differ from the accessible name. */
  title?: string
  variant?: IconButtonVariant
  size?: Size
}

/**
 * One token per square. The height comes from --height-icon-* (Task 1) and the
 * width reads the *same* variable through the arbitrary-property syntax rather
 * than a parallel --width-icon-* scale: two tokens describing one square is two
 * things to keep in sync, and they will drift.
 */
const DIMENSION: Record<Size, string> = {
  sm: 'h-icon-sm w-(--height-icon-sm)',
  md: 'h-icon-md w-(--height-icon-md)',
  lg: 'h-icon-lg w-(--height-icon-lg)',
}

const VARIANT: Record<IconButtonVariant, string> = {
  surface: 'bg-surface-3 text-text-mid border border-border ui-hover-surface',
  ghost: 'bg-transparent text-text-mute hover:text-text',
  danger: 'bg-transparent text-danger hover:bg-danger/15',
}

/**
 * `title` is additive, never a replacement for `aria-label` (design §4.8).
 * e2e selects on `button[title="Delete"]` in three places and a unit test
 * uses getByTitle, so dropping the attribute in favour of aria-label alone
 * breaks required checks.
 */
export default function IconButton({
  icon: Icon,
  label,
  title,
  variant = 'ghost',
  size = 'md',
  type = 'button',
  className = '',
  ...rest
}: IconButtonProps) {
  return (
    <button
      type={type}
      aria-label={label}
      title={title ?? label}
      className={[
        'ui-focus-ring ui-motion ui-disabled cursor-pointer inline-flex items-center justify-center rounded-icon',
        DIMENSION[size],
        VARIANT[variant],
        className,
      ]
        .filter(Boolean)
        .join(' ')}
      {...rest}
    >
      <Icon aria-hidden="true" className="h-4 w-4" />
    </button>
  )
}
