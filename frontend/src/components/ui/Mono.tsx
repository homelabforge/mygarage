import type { ElementType, ReactNode } from 'react'
import type { Tone } from './types'

type MonoSize = 'xs' | 'sm' | 'base' | 'lg' | 'xl' | '2xl'
type MonoWeight = 'medium' | 'semibold' | 'bold'

interface MonoProps {
  children: ReactNode
  /** Element to render. Defaults to `span`; use `td` inside DataTable. */
  as?: ElementType
  size?: MonoSize
  weight?: MonoWeight
  tone?: Tone
  /** Fixed-width digits. On by default — the whole point of mono figures is
   *  that a column of them lines up. Turn off for identifier strings where
   *  proportional glyphs read better. */
  tabular?: boolean
  align?: 'left' | 'right'
  /** `vin` adds the prototype's .02em tracking (dc.html:205, 266). */
  variant?: 'default' | 'vin'
  className?: string
}

const SIZE: Record<MonoSize, string> = {
  xs: 'text-[10.5px]',
  sm: 'text-[11.5px]',
  base: 'text-[12.5px]',
  lg: 'text-[14px]',
  xl: 'text-[17px]',
  '2xl': 'text-[22px]',
}

const WEIGHT: Record<MonoWeight, string> = {
  medium: 'font-medium',
  semibold: 'font-semibold',
  bold: 'font-bold',
}

/** Status tones are fixed and never accent-derived (design §4.9). */
const TONE: Record<Tone, string> = {
  default: 'text-text',
  muted: 'text-text-mute',
  accent: 'text-(--accent-fg)',
  success: 'text-success',
  warning: 'text-warning',
  danger: 'text-danger',
  info: 'text-info',
}

/**
 * Monospaced technical value — VIN, currency, date, count, percentage, ID.
 *
 * The prototype's rule (handoff README §Typography) is that *all* technical
 * and numeric values are JetBrains Mono. Today the app monospaces only
 * identifier strings, so migrating call sites to this primitive is most of
 * the visual delta between the current UI and the approved screenshots.
 */
export default function Mono({
  children,
  as: Tag = 'span',
  size = 'base',
  weight = 'medium',
  tone = 'default',
  tabular = true,
  align,
  variant = 'default',
  className = '',
}: MonoProps) {
  const classes = [
    'font-mono',
    SIZE[size],
    WEIGHT[weight],
    TONE[tone],
    tabular ? 'tabular-nums' : '',
    align === 'right' ? 'text-right' : '',
    variant === 'vin' ? 'tracking-[.02em]' : '',
    className,
  ]
    .filter(Boolean)
    .join(' ')

  return <Tag className={classes}>{children}</Tag>
}
