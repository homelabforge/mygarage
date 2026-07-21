/** Shared types for the primitive library. Declared once so 26 files do not
 *  each invent their own 'sm' | 'md' | 'lg'. */

import type { ComponentType, SVGProps } from 'react'

/** Every icon prop in the library. lucide-react icons satisfy this, and
 *  SVGProps permits aria-hidden="true" as a string — a bare
 *  ComponentType<{'aria-hidden'?: boolean}> does not, and fails tsc. */
export type IconType = ComponentType<SVGProps<SVGSVGElement>>

export type Size = 'sm' | 'md' | 'lg'

/** Semantic colour roles. Status tones are fixed and never accent-derived
 *  (design §4.9); `accent` follows the user's accent selection. */
export type Tone =
  | 'default'
  | 'muted'
  | 'accent'
  | 'success'
  | 'warning'
  | 'danger'
  | 'info'
