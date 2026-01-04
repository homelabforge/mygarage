/**
 * Category toggle switch component for POI search.
 * Red (disabled) / Green (enabled) toggle switch.
 */

import type { POICategory } from '../types/poi'

interface CategoryToggleProps {
  label: string
  category: POICategory
  enabled: boolean
  onToggle: (enabled: boolean) => void
}

export default function CategoryToggle({
  label,
  enabled,
  onToggle,
}: CategoryToggleProps) {
  return (
    <div className="flex items-center gap-3">
      <span className="text-sm font-medium text-gray-700 dark:text-gray-300 min-w-32">
        {label}
      </span>
      <button
        type="button"
        onClick={() => onToggle(!enabled)}
        className={`
          relative w-14 h-7 rounded-full transition-colors duration-200 ease-in-out
          ${enabled ? 'bg-green-500' : 'bg-red-500'}
          hover:opacity-90
          focus:outline-none focus:ring-2 focus:ring-offset-2
          ${enabled ? 'focus:ring-green-500' : 'focus:ring-red-500'}
        `}
        aria-label={`Toggle ${label}`}
        aria-pressed={enabled}
      >
        <span
          className={`
            absolute top-1 left-1 w-5 h-5 bg-white rounded-full
            transition-transform duration-200 ease-in-out shadow-md
            ${enabled ? 'translate-x-7' : 'translate-x-0'}
          `}
        />
      </button>
      <span className="text-xs text-gray-500 dark:text-gray-400">
        {enabled ? 'On' : 'Off'}
      </span>
    </div>
  )
}
