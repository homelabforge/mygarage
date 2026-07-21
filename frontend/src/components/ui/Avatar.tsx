import type { Size } from './types'

interface AvatarProps {
  /** Full name. Drives both the initials and the accessible name. */
  name: string
  src?: string
  size?: Size
  className?: string
}

const DIMENSION: Record<Size, string> = {
  sm: 'h-7 w-7 text-[10px]',
  md: 'h-9 w-9 text-xs',
  lg: 'h-12 w-12 text-sm',
}

/** First letter of the first two words. "Jamey Starett" → "JS". */
function initialsOf(name: string): string {
  return name
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]!.toUpperCase())
    .join('')
}

/**
 * Gradient initials circle, or a photo when one exists.
 *
 * Nothing like this exists today — Layout renders a bare lucide User icon.
 * The gradient runs through the accent so the nav avatar tracks the user's
 * accent choice.
 */
export default function Avatar({ name, src, size = 'md', className = '' }: AvatarProps) {
  const initials = initialsOf(name)

  if (src) {
    return (
      <img
        src={src}
        alt={name}
        className={`${DIMENSION[size]} rounded-full object-cover ${className}`}
      />
    )
  }

  return (
    <span
      role="img"
      aria-label={name}
      className={`${DIMENSION[size]} inline-flex items-center justify-center rounded-full bg-linear-to-br from-(--accent) to-(--accent-solid) font-semibold text-(--accent-on-solid) ${className}`}
    >
      {/* aria-hidden: the accessible name is the full name on the wrapper,
          not the two letters, which read as nonsense to a screen reader. */}
      <span aria-hidden="true">{initials}</span>
    </span>
  )
}
