import { useState, useEffect, useRef, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { Plus, X } from 'lucide-react'
import type { AddressBookEntry } from '../types/addressBook'
import api from '../services/api'

interface AddressBookAutocompleteProps {
  value: string
  onChange: (value: string) => void
  onSelectEntry?: (entry: AddressBookEntry | null) => void
  categoryFilter?: string
  poiCategoryFilter?: string
  /** Defaults to the translated generic search placeholder when omitted. */
  placeholder?: string
  className?: string
  id?: string
  helperText?: string
  /**
   * Optional handler for the clear (X) button rendered inside the input
   * when ``value`` is non-empty. Surfaced by issue #69 — rc1 had no way
   * to remove a previously entered fueling station except by manually
   * deleting all the typed characters.
   */
  onClear?: () => void
  /**
   * Optional handler invoked when the user clicks "+ Add 'X'" in the
   * empty-results dropdown footer. The string passed back is whatever
   * the user has typed. Surfaced by issue #69 — rc1 had no way to add
   * a new station to the address book without leaving the fuel form.
   */
  onAddNew?: (typedName: string) => void
}

export default function AddressBookAutocomplete({
  value,
  onChange,
  onSelectEntry,
  categoryFilter,
  poiCategoryFilter,
  placeholder,
  className = '',
  id,
  helperText,
  onClear,
  onAddNew,
}: AddressBookAutocompleteProps) {
  const { t } = useTranslation('common')
  const [entries, setEntries] = useState<AddressBookEntry[]>([])
  const [loading, setLoading] = useState(false)
  const [showDropdown, setShowDropdown] = useState(false)
  const [selectedIndex, setSelectedIndex] = useState(-1)
  const wrapperRef = useRef<HTMLDivElement>(null)
  // Only what the user typed gets searched. Picks, quick add and an edit form's
  // saved name write the value too, and searching those reopened the list (#194).
  const typedRef = useRef<string | null>(null)
  // Every search takes a number and a stale one is dropped, so a slow answer
  // can't reopen a list a pick or clear just closed.
  const requestIdRef = useRef(0)
  // The deps take this instead of onAddNew: callers pass inline functions, and
  // a new one each render refired the search.
  const hasAddNew = !!onAddNew

  // Drops the running search. It clears the spinner too, because a dropped
  // search skips its own finally.
  const invalidate = useCallback((): void => {
    requestIdRef.current += 1
    setLoading(false)
  }, [])

  // Search for entries when value changes
  useEffect(() => {
    // Runs before the typed check: the clear button empties the value from the
    // parent, and that still has to close the list.
    if (!value || value.length < 2) {
      setEntries([])
      setShowDropdown(false)
      invalidate()
      return
    }

    const searchEntries = async (): Promise<void> => {
      // Checked when the timer fires, not when it's set: picking the name that's
      // already typed leaves the value alone, so nothing cancels this timer.
      if (value !== typedRef.current) return
      const id = ++requestIdRef.current
      try {
        setLoading(true)
        const params = new URLSearchParams()
        params.append('search', value)
        if (categoryFilter) params.append('category', categoryFilter)
        if (poiCategoryFilter) params.append('poi_category', poiCategoryFilter)

        const response = await api.get(`/address-book?${params}`)
        if (id !== requestIdRef.current) return
        const fetched = response.data.entries || []
        setEntries(fetched)
        // Show the dropdown when there are results OR when the empty-state
        // has actionable affordances (the "+ Add to address book" footer
        // shipped in v2.27.0-rc2). Without this, an empty result hides the
        // entire dropdown and the user has no way to reach the modal.
        setShowDropdown(fetched.length > 0 || hasAddNew)
      } catch {
        if (id === requestIdRef.current) setEntries([])
      } finally {
        if (id === requestIdRef.current) setLoading(false)
      }
    }

    // Debounce the search
    const timeoutId = setTimeout(searchEntries, 300)
    // A new value, a filter change or unmount drops the search this run started,
    // so a late answer can't open the list for text that's no longer in the box.
    return () => {
      clearTimeout(timeoutId)
      invalidate()
    }
  }, [value, categoryFilter, poiCategoryFilter, hasAddNew, invalidate])

  // Close dropdown when clicking outside. Like Escape, this drops the search
  // too, or its answer reopens the list after you've moved on.
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(event.target as Node)) {
        typedRef.current = null
        invalidate()
        setShowDropdown(false)
      }
    }

    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [invalidate])

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>): void => {
    typedRef.current = e.target.value
    onChange(e.target.value)
    setSelectedIndex(-1)
  }

  const handleSelectEntry = (entry: AddressBookEntry): void => {
    // The pick writes the value and the value drives the search, so the picked
    // name must not count as typed, and a search still out must not land.
    typedRef.current = null
    invalidate()
    onChange(entry.business_name || entry.name || '')
    // The matches were for the text typed before the pick. Kept, focus would
    // reopen them under the picked name.
    setEntries([])
    setShowDropdown(false)
    if (onSelectEntry) {
      onSelectEntry(entry)
    }
  }

  const handleClear = (): void => {
    typedRef.current = null
    invalidate()
    onClear?.()
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!showDropdown || entries.length === 0) return

    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault()
        setSelectedIndex(prev => (prev < entries.length - 1 ? prev + 1 : prev))
        break
      case 'ArrowUp':
        e.preventDefault()
        setSelectedIndex(prev => (prev > 0 ? prev - 1 : -1))
        break
      case 'Enter':
        e.preventDefault()
        if (selectedIndex >= 0 && selectedIndex < entries.length) {
          handleSelectEntry(entries[selectedIndex])
        }
        break
      case 'Escape':
        // Closing drops the search still waiting or running, so it can't
        // reopen the list. Typing again starts a fresh one.
        typedRef.current = null
        invalidate()
        setShowDropdown(false)
        setSelectedIndex(-1)
        break
    }
  }

  const formatEntryDisplay = (entry: AddressBookEntry): string => {
    const parts = []
    if (entry.business_name) parts.push(entry.business_name)
    if (entry.name && entry.business_name !== entry.name) parts.push(`(${entry.name})`)
    if (entry.city && entry.state) parts.push(`- ${entry.city}, ${entry.state}`)
    else if (entry.city) parts.push(`- ${entry.city}`)
    return parts.join(' ')
  }

  return (
    <div ref={wrapperRef} className="relative">
      <input
        type="text"
        id={id}
        value={value}
        onChange={handleInputChange}
        onKeyDown={handleKeyDown}
        onFocus={() => value.length >= 2 && entries.length > 0 && setShowDropdown(true)}
        placeholder={placeholder ?? t('addressBookAutocomplete.placeholder')}
        className={`${className} ${onClear && value ? 'pr-10' : ''}`}
        autoComplete="off"
      />

      {loading && (
        <div className="absolute right-3 top-1/2 -translate-y-1/2">
          <div className="w-4 h-4 border-2 border-primary border-t-transparent rounded-full animate-spin"></div>
        </div>
      )}

      {!loading && onClear && value && (
        <button
          type="button"
          onClick={handleClear}
          aria-label={t('addressBookAutocomplete.clear')}
          className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-garage-text-muted hover:text-garage-text rounded hover:bg-garage-bg"
        >
          <X className="w-4 h-4" />
        </button>
      )}

      {showDropdown && entries.length > 0 && (
        <div className="absolute z-50 w-full mt-1 bg-garage-surface border border-garage-border rounded-md shadow-lg max-h-60 overflow-y-auto">
          {entries.map((entry, index) => (
            <button
              key={entry.id}
              type="button"
              onClick={() => handleSelectEntry(entry)}
              className={`w-full text-left px-3 py-2 hover:bg-garage-bg transition-colors ${
                index === selectedIndex ? 'bg-garage-bg' : ''
              }`}
            >
              <div className="text-sm text-garage-text">{formatEntryDisplay(entry)}</div>
              {entry.address && (
                <div className="text-xs text-garage-text-muted mt-0.5">{entry.address}</div>
              )}
            </button>
          ))}
        </div>
      )}

      {!loading && value.length >= 2 && entries.length === 0 && showDropdown && (
        <div className="absolute z-50 w-full mt-1 bg-garage-surface border border-garage-border rounded-md shadow-lg">
          {/* ``query``/``category`` are user-entered — interpolated as data,
              never used as a translation key. */}
          <p className="text-sm text-garage-text-muted p-3">
            {categoryFilter
              ? t('addressBookAutocomplete.noMatchesInCategory', {
                  query: value,
                  category: categoryFilter,
                })
              : t('addressBookAutocomplete.noMatches', { query: value })}
          </p>
          {onAddNew && (
            <button
              type="button"
              onClick={() => {
                onAddNew(value)
                setShowDropdown(false)
              }}
              className="w-full text-left px-3 py-2 border-t border-garage-border hover:bg-garage-bg transition-colors flex items-center gap-2 text-sm text-(--accent-fg)"
            >
              <Plus className="w-4 h-4" />
              <span>{t('addressBookAutocomplete.addToAddressBook', { query: value })}</span>
            </button>
          )}
        </div>
      )}

      {helperText !== undefined ? (
        <p className="text-xs text-garage-text-muted mt-1">{helperText}</p>
      ) : (
        <p className="text-xs text-garage-text-muted mt-1">
          {t('addressBookAutocomplete.helperText')}
        </p>
      )}
    </div>
  )
}
