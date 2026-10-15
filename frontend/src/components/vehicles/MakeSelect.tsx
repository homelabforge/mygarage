import { useState, useRef, useEffect, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronDown, X } from 'lucide-react'
import BrandLogo from './BrandLogo'
import { getAllMakes, findMake, type CarMake } from '../../services/carCatalogService'

export interface MakeSelectProps {
  id?: string
  value: string | null | undefined
  onChange: (value: string) => void
  disabled?: boolean
  invalid?: boolean
  placeholder?: string
  className?: string
}

export default function MakeSelect({
  id,
  value,
  onChange,
  disabled = false,
  invalid = false,
  placeholder,
  className = '',
}: MakeSelectProps) {
  const { t } = useTranslation('vehicles')
  const [isOpen, setIsOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [highlightedIndex, setHighlightedIndex] = useState(-1)
  const containerRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLUListElement>(null)

  const allMakes = useMemo(() => getAllMakes(), [])

  // Matched make object for current value
  const currentMake = useMemo(() => findMake(value), [value])

  // Display value for input when not actively typing in open dropdown
  const displayValue = isOpen ? search : value || ''

  // Filtered makes based on search
  const filteredMakes = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return allMakes
    return allMakes.filter(m => m.name.toLowerCase().includes(q))
  }, [allMakes, search])

  // Does the search exactly match one of the filtered makes?
  const hasExactMatch = useMemo(() => {
    const q = search.trim().toLowerCase()
    return filteredMakes.some(m => m.name.toLowerCase() === q)
  }, [filteredMakes, search])

  // Show custom option if search has text and no exact match
  const showCustomOption = Boolean(search.trim() && !hasExactMatch)

  // Total items in dropdown
  const totalOptions = filteredMakes.length + (showCustomOption ? 1 : 0)

  // Close on outside click
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false)
        setSearch('')
        setHighlightedIndex(-1)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  // Auto-scroll highlighted option into view
  useEffect(() => {
    if (highlightedIndex >= 0 && listRef.current) {
      const items = listRef.current.querySelectorAll('li')
      if (items[highlightedIndex]) {
        items[highlightedIndex].scrollIntoView?.({ block: 'nearest' })
      }
    }
  }, [highlightedIndex])

  const handleSelectMake = (make: CarMake) => {
    onChange(make.name)
    setIsOpen(false)
    setSearch('')
    setHighlightedIndex(-1)
    inputRef.current?.blur()
  }

  const handleSelectCustom = (customName: string) => {
    onChange(customName.trim())
    setIsOpen(false)
    setSearch('')
    setHighlightedIndex(-1)
    inputRef.current?.blur()
  }

  const handleClear = (e: React.MouseEvent) => {
    e.stopPropagation()
    onChange('')
    setSearch('')
    setHighlightedIndex(-1)
    inputRef.current?.focus()
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (disabled) return

    if (!isOpen) {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp' || e.key === 'Enter') {
        e.preventDefault()
        setIsOpen(true)
        setSearch('')
        setHighlightedIndex(0)
      }
      return
    }

    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault()
        setHighlightedIndex(prev => (prev < totalOptions - 1 ? prev + 1 : 0))
        break
      case 'ArrowUp':
        e.preventDefault()
        setHighlightedIndex(prev => (prev > 0 ? prev - 1 : totalOptions - 1))
        break
      case 'Enter':
        e.preventDefault()
        if (showCustomOption && highlightedIndex === 0) {
          handleSelectCustom(search)
        } else {
          const makeIndex = showCustomOption ? highlightedIndex - 1 : highlightedIndex
          if (makeIndex >= 0 && makeIndex < filteredMakes.length) {
            handleSelectMake(filteredMakes[makeIndex])
          } else if (search.trim()) {
            handleSelectCustom(search)
          }
        }
        break
      case 'Escape':
        e.preventDefault()
        setIsOpen(false)
        setSearch('')
        setHighlightedIndex(-1)
        break
      case 'Tab':
        setIsOpen(false)
        setSearch('')
        setHighlightedIndex(-1)
        break
    }
  }

  return (
    <div ref={containerRef} className="relative w-full">
      <div className="relative flex items-center">
        {/* Brand logo prefix inside input */}
        <div className="absolute left-2.5 flex items-center pointer-events-none z-10">
          <BrandLogo make={currentMake ? currentMake.name : value} className="w-7 h-7" />
        </div>

        <input
          ref={inputRef}
          id={id}
          type="text"
          role="combobox"
          aria-expanded={isOpen}
          aria-autocomplete="list"
          disabled={disabled}
          value={displayValue}
          onKeyDown={handleKeyDown}
          onChange={(e) => {
            setSearch(e.target.value)
            setHighlightedIndex(0)
            if (!isOpen) setIsOpen(true)
          }}
          onFocus={() => {
            if (!isOpen) {
              setIsOpen(true)
              setSearch('')
              setHighlightedIndex(0)
            }
          }}
          placeholder={placeholder || t('wizard.misc.makePlaceholder', 'Search or select make...')}
          className={`w-full bg-surface border rounded-control pl-12 pr-16 py-2.5 text-text text-sm focus:outline-none focus:border-(--accent-solid) transition-colors ${
            invalid ? 'border-danger' : 'border-border'
          } ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-text'} ${className}`}
          autoComplete="off"
        />

        <div className="absolute right-2.5 flex items-center gap-1">
          {Boolean(value) && !disabled && (
            <button
              type="button"
              onClick={handleClear}
              aria-label={t('common:clear', 'Clear')}
              className="p-1 text-text-mute hover:text-text rounded hover:bg-surface-2 transition-colors"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
          <button
            type="button"
            tabIndex={-1}
            disabled={disabled}
            onClick={() => {
              if (isOpen) {
                setIsOpen(false)
              } else {
                setIsOpen(true)
                setSearch('')
                setHighlightedIndex(0)
                inputRef.current?.focus()
              }
            }}
            className="p-1 text-text-mute hover:text-text rounded transition-colors"
          >
            <ChevronDown className={`w-4 h-4 transition-transform ${isOpen ? 'rotate-180' : ''}`} />
          </button>
        </div>
      </div>

      {isOpen && (
        <ul
          ref={listRef}
          role="listbox"
          className="absolute z-50 w-full mt-1.5 max-h-72 overflow-y-auto bg-surface border border-border rounded-control shadow-xl py-1.5 text-sm focus:outline-none"
        >
          {showCustomOption && (
            <li
              role="option"
              aria-selected={highlightedIndex === 0}
              onClick={() => handleSelectCustom(search)}
              onMouseEnter={() => setHighlightedIndex(0)}
              className={`px-3 py-2.5 flex items-center gap-3 cursor-pointer text-text hover:bg-surface-2 transition-colors ${
                highlightedIndex === 0 ? 'bg-surface-2' : ''
              }`}
            >
              <BrandLogo make={null} className="w-9 h-9 opacity-70" />
              <div className="flex-1 truncate">
                <span className="text-text-mute">{t('wizard.misc.useCustomMake', 'Use')}: </span>
                <span className="font-semibold text-text">"{search.trim()}"</span>
              </div>
            </li>
          )}

          {filteredMakes.map((make, index) => {
            const actualIndex = showCustomOption ? index + 1 : index
            const isSelected = (value || '').toLowerCase() === make.name.toLowerCase()
            const isHighlighted = highlightedIndex === actualIndex

            return (
              <li
                key={make.slug}
                role="option"
                aria-selected={isSelected}
                onClick={() => handleSelectMake(make)}
                onMouseEnter={() => setHighlightedIndex(actualIndex)}
                className={`px-3 py-2.5 flex items-center gap-3 cursor-pointer text-text hover:bg-surface-2 transition-colors ${
                  isHighlighted ? 'bg-surface-2' : ''
                } ${isSelected ? 'font-semibold text-(--accent-solid)' : ''}`}
              >
                <BrandLogo make={make.name} logoSlug={make.logo} className="w-9 h-9" />
                <span className="truncate flex-1 font-medium">{make.name}</span>
                {isSelected && (
                  <span className="text-xs text-text-mute">
                    {t('common:selected', 'Selected')}
                  </span>
                )}
              </li>
            )
          })}

          {filteredMakes.length === 0 && !showCustomOption && (
            <li className="px-3 py-3 text-center text-text-mute text-xs">
              {t('wizard.misc.noMakesFound', 'No makes found')}
            </li>
          )}
        </ul>
      )}
    </div>
  )
}
