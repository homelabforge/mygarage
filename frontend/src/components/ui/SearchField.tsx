import { Search } from 'lucide-react'
import Input from './Input'
import type { Size } from './types'

interface SearchFieldProps {
  value: string
  onChange: (next: string) => void
  /** Accessible name. Search fields rarely carry a visible label. */
  label: string
  placeholder?: string
  size?: Size
  className?: string
}

/**
 * Search input with a leading glyph. Replaces six copies of the same
 * relative-wrapper + absolute-icon + padded-input pattern whose icon size
 * had drifted between w-4 and w-5.
 *
 * Composes `Input` for real: `Input` already forwards `type` untouched
 * (task 9's "implicit roles hang off it" contract) and already owns a
 * leading-adornment slot via `prefix` (the same relative-wrapper +
 * absolute-icon + padded-input mechanics this component would otherwise
 * reimplement). So `type="search"` plus `prefix={<Search .../>}` gets the
 * searchbox role and the icon padding from the single place that already
 * defines them, instead of a second height map and a second copy of the
 * pattern this primitive exists to delete.
 *
 * type="search" gives the searchbox role, which is more precise than
 * textbox and is not pinned by any existing test (no current search input
 * is queried by role).
 */
export default function SearchField({
  value,
  onChange,
  label,
  placeholder,
  size = 'md',
  className = '',
}: SearchFieldProps) {
  return (
    <Input
      type="search"
      aria-label={label}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      size={size}
      className={className}
      prefix={<Search aria-hidden="true" className="h-4 w-4" />}
    />
  )
}
