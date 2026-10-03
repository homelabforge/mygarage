import { useState, useRef, useEffect, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronDown, X, Globe, Loader2 } from 'lucide-react'
import { getModelsForMake, fetchNhtsaModels } from '../../services/carCatalogService'

export interface ModelSelectProps {
  id?: string
  make?: string | null | undefined
  value: string | null | undefined
  onChange: (value: string) => void
  disabled?: boolean
  invalid?: boolean
  placeholder?: string
  className?: string
}

export default function ModelSelect({
  id,
  make,
  value,
  onChange,
  disabled = false,
  invalid = false,
  placeholder,
  className = '',
}: ModelSelectProps) {
  const { t } = useTranslation('vehicles')
  const [isOpen, setIsOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [highlightedIndex, setHighlightedIndex] = useState(-1)
  const [extraModels, setExtraModels] = useState<string[]>([])
  const [isFetchingNhtsa, setIsFetchingNhtsa] = useState(false)
  const [nhtsaFetchedFor, setNhtsaFetchedFor] = useState<string | null>(null)

  const containerRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLUListElement>(null)

  // Reset extra models when make changes
  useEffect(() => {
    setExtraModels([])
    setNhtsaFetchedFor(null)
  }, [make])

  // Catalog models for the selected make
  const catalogModels = useMemo(() => {
    if (!make) return []
    return getModelsForMake(make)
  }, [make])

  // Combined models (catalog + extra from NHTSA)
  const availableModels = useMemo(() => {
    const set = new Set<string>()
    for (const m of catalogModels) set.add(m)
    for (const m of extraModels) set.add(m)
    return Array.from(set).sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base' }))
  }, [catalogModels, extraModels])

  // Display value for input
  const displayValue = isOpen ? search : value || ''

  // Filtered models based on search
  const filteredModels = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return availableModels
    return availableModels.filter(m => m.toLowerCase().includes(q))
  }, [availableModels, search])

  // Check exact match
  const hasExactMatch = useMemo(() => {
    const q = search.trim().toLowerCase()
    return filteredModels.some(m => m.toLowerCase() === q)
  }, [filteredModels, search])

  // Show custom option if search has text and no exact match
  const showCustomOption = Boolean(search.trim() && !hasExactMatch)

  // Total items in dropdown
  const canFetchNhtsa = Boolean(make && make.trim() && nhtsaFetchedFor !== make.trim())
  const totalOptions = filteredModels.length + (showCustomOption ? 1 : 0)

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

  const handleSelectModel = (model: string) => {
    onChange(model)
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

  const handleFetchNhtsa = async (e: React.MouseEvent) => {
    e.stopPropagation()
    if (!make || isFetchingNhtsa) return

    setIsFetchingNhtsa(true)
    try {
      const nhtsaModels = await fetchNhtsaModels(make)
      setExtraModels(nhtsaModels)
      setNhtsaFetchedFor(make.trim())
    } finally {
      setIsFetchingNhtsa(false)
    }
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
          const modelIndex = showCustomOption ? highlightedIndex - 1 : highlightedIndex
          if (modelIndex >= 0 && modelIndex < filteredModels.length) {
            handleSelectModel(filteredModels[modelIndex])
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

  const resolvedPlaceholder =
    placeholder ||
    (make
      ? t('wizard.misc.modelPlaceholder', 'Model')
      : t('wizard.misc.selectMakeFirst', 'Select make first or enter model'))

  return (
    <div ref={containerRef} className="relative w-full">
      <div className="relative flex items-center">
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
          placeholder={resolvedPlaceholder}
          className={`w-full bg-surface border rounded-control px-4 pr-16 py-2 text-text text-sm focus:outline-none focus:border-(--accent-solid) transition-colors ${
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
        <div className="absolute z-50 w-full mt-1.5 bg-surface border border-border rounded-control shadow-xl text-sm overflow-hidden">
          <ul
            ref={listRef}
            role="listbox"
            className="max-h-60 overflow-y-auto py-1 focus:outline-none"
          >
            {showCustomOption && (
              <li
                role="option"
                aria-selected={highlightedIndex === 0}
                onClick={() => handleSelectCustom(search)}
                onMouseEnter={() => setHighlightedIndex(0)}
                className={`px-3 py-2 cursor-pointer text-text hover:bg-surface-2 transition-colors ${
                  highlightedIndex === 0 ? 'bg-surface-2' : ''
                }`}
              >
                <span className="text-text-mute">{t('wizard.misc.useCustomModel', 'Use')}: </span>
                <span className="font-semibold text-text">"{search.trim()}"</span>
              </li>
            )}

            {filteredModels.map((modelName, index) => {
              const actualIndex = showCustomOption ? index + 1 : index
              const isSelected = (value || '').toLowerCase() === modelName.toLowerCase()
              const isHighlighted = highlightedIndex === actualIndex

              return (
                <li
                  key={modelName}
                  role="option"
                  aria-selected={isSelected}
                  onClick={() => handleSelectModel(modelName)}
                  onMouseEnter={() => setHighlightedIndex(actualIndex)}
                  className={`px-3 py-2 flex items-center justify-between cursor-pointer text-text hover:bg-surface-2 transition-colors ${
                    isHighlighted ? 'bg-surface-2' : ''
                  } ${isSelected ? 'font-semibold text-(--accent-solid)' : ''}`}
                >
                  <span className="truncate">{modelName}</span>
                  {isSelected && (
                    <span className="text-xs text-text-mute">
                      {t('common:selected', 'Selected')}
                    </span>
                  )}
                </li>
              )
            })}

            {filteredModels.length === 0 && !showCustomOption && (
              <li className="px-3 py-3 text-center text-text-mute text-xs">
                {make
                  ? t('wizard.misc.noModelsFound', 'No models found for this make')
                  : t('wizard.misc.selectMakePrompt', 'Select a make to see available models')}
              </li>
            )}
          </ul>

          {/* NHTSA online search fallback footer */}
          {canFetchNhtsa && (
            <div className="border-t border-border p-1.5 bg-surface-2/50">
              <button
                type="button"
                onClick={handleFetchNhtsa}
                disabled={isFetchingNhtsa}
                className="w-full flex items-center justify-center gap-1.5 py-1.5 px-2 text-xs text-text-mid hover:text-text hover:bg-surface-2 rounded transition-colors"
              >
                {isFetchingNhtsa ? (
                  <>
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    <span>{t('wizard.misc.loadingOnlineModels', 'Searching online models...')}</span>
                  </>
                ) : (
                  <>
                    <Globe className="w-3.5 h-3.5 text-text-mute" />
                    <span>{t('wizard.misc.fetchMoreModelsOnline', 'Search NHTSA online models')}</span>
                  </>
                )}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
