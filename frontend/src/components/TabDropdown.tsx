import { useState, useEffect, useRef } from 'react'
import { ChevronDown } from 'lucide-react'

interface DropdownItem {
  id: string
  label: string
  icon: React.ComponentType<{ className?: string }>
  onClick: () => void
}

interface TabDropdownProps {
  label: string
  icon: React.ComponentType<{ className?: string }>
  isActive: boolean
  isOpen: boolean
  onToggle: () => void
  items: DropdownItem[]
}

export default function TabDropdown({
  label,
  icon: Icon,
  isActive,
  isOpen,
  onToggle,
  items,
}: TabDropdownProps) {
  const dropdownRef = useRef<HTMLDivElement>(null)
  const [focusedIndex, setFocusedIndex] = useState(-1)

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        if (isOpen) {
          onToggle()
        }
      }
    }

    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [isOpen, onToggle])

  // Keyboard navigation
  const handleKeyDown = (event: React.KeyboardEvent) => {
    if (!isOpen) {
      if (event.key === 'Enter' || event.key === ' ' || event.key === 'ArrowDown') {
        event.preventDefault()
        onToggle()
        setFocusedIndex(0)
      }
      return
    }

    switch (event.key) {
      case 'Escape':
        event.preventDefault()
        onToggle()
        setFocusedIndex(-1)
        break
      case 'ArrowDown':
        event.preventDefault()
        setFocusedIndex((prev) => (prev + 1) % items.length)
        break
      case 'ArrowUp':
        event.preventDefault()
        setFocusedIndex((prev) => (prev - 1 + items.length) % items.length)
        break
      case 'Enter':
      case ' ':
        event.preventDefault()
        if (focusedIndex >= 0) {
          items[focusedIndex].onClick()
        }
        break
    }
  }

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        onClick={onToggle}
        onKeyDown={handleKeyDown}
        className={`flex items-center space-x-2 px-4 py-3 border-b-2 transition-colors ${
          isActive
            ? 'border-primary text-primary'
            : 'border-transparent text-garage-text-muted hover:text-garage-text hover:border-garage-border'
        }`}
        aria-haspopup="true"
        aria-expanded={isOpen}
      >
        <Icon className="w-4 h-4" />
        <span>{label}</span>
        <ChevronDown
          className={`w-4 h-4 transition-transform ${isOpen ? 'rotate-180' : ''}`}
        />
      </button>

      {isOpen && (
        <div
          className="absolute top-full left-0 mt-1 bg-garage-surface border border-garage-border rounded-lg shadow-lg overflow-hidden z-50 min-w-[200px]"
          role="menu"
        >
          {items.map((item, index) => {
            const ItemIcon = item.icon
            return (
              <button
                key={item.id}
                onClick={item.onClick}
                onMouseEnter={() => setFocusedIndex(index)}
                className={`w-full flex items-center space-x-2 px-4 py-3 text-left transition-colors ${
                  focusedIndex === index
                    ? 'bg-primary/10 text-primary'
                    : 'text-garage-text hover:bg-garage-bg'
                }`}
                role="menuitem"
              >
                <ItemIcon className="w-4 h-4" />
                <span>{item.label}</span>
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
