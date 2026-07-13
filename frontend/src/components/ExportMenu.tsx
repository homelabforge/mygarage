import { useState, useEffect, useRef } from 'react'
import { ChevronDown } from 'lucide-react'

interface ExportMenuProps {
  onExportCSV: () => void
  onExportPDF: () => void
  disabled?: boolean
}

/**
 * Single "Export" header button that drops down to CSV / PDF choices, matching
 * the MyFinances pattern. Replaces the side-by-side CSV + PDF buttons, which
 * overflowed narrow screens. Closes on outside click and Escape; supports
 * arrow-key navigation.
 */
export default function ExportMenu({ onExportCSV, onExportPDF, disabled = false }: ExportMenuProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [focusedIndex, setFocusedIndex] = useState(-1)
  const containerRef = useRef<HTMLDivElement>(null)

  const items = [
    { id: 'csv', label: 'CSV', onClick: onExportCSV },
    { id: 'pdf', label: 'PDF', onClick: onExportPDF },
  ]

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent): void => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setIsOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const select = (onClick: () => void): void => {
    setIsOpen(false)
    setFocusedIndex(-1)
    onClick()
  }

  const handleKeyDown = (event: React.KeyboardEvent): void => {
    if (!isOpen) {
      if (event.key === 'ArrowDown' || event.key === 'Enter' || event.key === ' ') {
        event.preventDefault()
        setIsOpen(true)
        setFocusedIndex(0)
      }
      return
    }
    switch (event.key) {
      case 'Escape':
        event.preventDefault()
        setIsOpen(false)
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
          select(items[focusedIndex].onClick)
        }
        break
    }
  }

  return (
    <div className="relative" ref={containerRef}>
      <button
        onClick={() => setIsOpen((open) => !open)}
        onKeyDown={handleKeyDown}
        disabled={disabled}
        className="px-4 py-2 bg-garage-surface border border-garage-border text-garage-text rounded-lg hover:bg-garage-surface-light transition-colors flex items-center gap-2 disabled:opacity-50"
        aria-haspopup="true"
        aria-expanded={isOpen}
      >
        <span>Export</span>
        <ChevronDown className={`w-4 h-4 transition-transform ${isOpen ? 'rotate-180' : ''}`} />
      </button>

      {isOpen && (
        <div
          className="absolute top-full right-0 mt-1 bg-garage-surface border border-garage-border rounded-lg shadow-lg overflow-hidden z-50 min-w-[8rem]"
          role="menu"
        >
          {items.map((item, index) => (
            <button
              key={item.id}
              onClick={() => select(item.onClick)}
              onMouseEnter={() => setFocusedIndex(index)}
              className={`w-full px-4 py-2.5 text-left transition-colors ${
                focusedIndex === index
                  ? 'bg-primary/10 text-primary'
                  : 'text-garage-text hover:bg-garage-bg'
              }`}
              role="menuitem"
            >
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
