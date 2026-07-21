/**
 * The primitive library's single import surface.
 *
 * This file is also the reachability root for everything under
 * `components/ui/`. `scripts/validate-reachability.ts` walks imports from
 * `src/main.tsx` and fails anything it cannot reach, with an ALLOWLIST that
 * is empty and stays empty — so a primitive missing from this barrel fails
 * CI. Add the export in the same commit as the component.
 *
 * This file is only reachable itself because the gallery imports through it
 * (`import { X } from '..'`). Nothing else in the app imports the barrel yet,
 * so if the gallery ever reaches around it to a component file directly, both
 * this file and ./types become unreachable and the gate fails.
 */

export type { IconType, Size, Tone } from './types'

// Primitives are appended here as each task lands (Tasks 4-23).
export { default as Mono } from './Mono'
export { default as Badge } from './Badge'
export { default as Chip } from './Chip'
export { default as Avatar } from './Avatar'
export { default as EmptyState } from './EmptyState'
export { default as PageContainer } from './PageContainer'
export { default as PageHeader } from './PageHeader'
export { default as Card } from './Card'
export { default as CardHeader } from './CardHeader'
export { default as Tile } from './Tile'
export { default as ListRow } from './ListRow'
export { default as Button } from './Button'
export { default as IconButton } from './IconButton'
export { default as Field } from './Field'
export { default as Input } from './Input'
export { default as Textarea } from './Textarea'
export { default as Select } from './Select'
export type { SelectOption } from './Select'
export { default as Checkbox } from './Checkbox'
export { default as Toggle } from './Toggle'
