import { useState, useEffect, useRef, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { Plus, X } from 'lucide-react'
import type { AddressBookEntry } from '../types/addressBook'
import api from '../services/api'
import { useCombobox } from './ui'

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
  // The text `entries` answer. Set together with them, so a panel never shows one
  // search's results (or its "No matches") under different text (G-3).
  const [answeredFor, setAnsweredFor] = useState<string | null>(null)
  const [searchFailed, setSearchFailed] = useState(false)
  const [loading, setLoading] = useState(false)
  const [showDropdown, setShowDropdown] = useState(false)
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
      setAnsweredFor(null)
      setShowDropdown(false)
      invalidate()
      return
    }
    // Text the parent wrote (a pick, quick add, a receipt scan) never gets searched, so
    // the list shuts rather than sitting on "Searching" for an answer that won't come.
    if (value !== typedRef.current) {
      setShowDropdown(false)
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
        setAnsweredFor(value)
        setSearchFailed(false)
        // Show the dropdown when there are results OR when the empty-state
        // has actionable affordances (the "+ Add to address book" footer
        // shipped in v2.27.0-rc2). Without this, an empty result hides the
        // entire dropdown and the user has no way to reach the modal.
        setShowDropdown(fetched.length > 0 || hasAddNew)
      } catch {
        // An error row, never "No matches": the search didn't say there were none.
        if (id === requestIdRef.current) {
          setEntries([])
          setAnsweredFor(value)
          setSearchFailed(true)
          setShowDropdown(true)
        }
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
    setAnsweredFor(null)
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

  const closeList = (): void => {
    // Closing drops the search still waiting or running, so it can't reopen the
    // list. Typing again starts a fresh one.
    typedRef.current = null
    invalidate()
    setShowDropdown(false)
  }

  // Not answered means a search for what's in the box is still out or waiting out
  // the debounce, so the panel shows "Searching" instead of old results.
  const answered = answeredFor === value && !loading
  const pending = showDropdown && !answered
  const showAddNew = answered && !searchFailed && entries.length === 0 && !!onAddNew
  const optionCount = answered ? entries.length + (showAddNew ? 1 : 0) : 0
  const canReopen = answeredFor === value && value.length >= 2 && entries.length > 0

  const handleAddNew = (): void => {
    onAddNew?.(value)
    setShowDropdown(false)
  }

  const combobox = useCombobox({
    id,
    open: showDropdown,
    count: optionCount,
    onSelect: (index) => (index < entries.length ? handleSelectEntry(entries[index]) : handleAddNew()),
    onClose: closeList,
    onOpen: () => canReopen && setShowDropdown(true),
  })

  let status = ''
  if (loading || pending) status = t('combobox.searching')
  else if (answered && searchFailed) status = t('combobox.searchFailed')
  else if (answered) {
    status = entries.length > 0 ? t('combobox.results', { count: entries.length }) : t('combobox.noResults')
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
        {...combobox.inputProps}
        value={value}
        onChange={handleInputChange}
        onFocus={() => canReopen && setShowDropdown(true)}
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

      {showDropdown && (
        <div className="absolute z-50 w-full mt-1 bg-garage-surface border border-garage-border rounded-md shadow-lg max-h-60 overflow-y-auto">
          {pending && (
            <p className="text-sm text-garage-text-muted px-3 py-2">{t('addressBookAutocomplete.searching')}</p>
          )}
          {answered && searchFailed && (
            <p className="text-sm text-garage-text-muted p-3">{t('addressBookAutocomplete.searchFailed')}</p>
          )}
          {answered && !searchFailed && entries.length === 0 && (
            // ``query``/``category`` are user-entered, interpolated as data and
            // never used as a translation key.
            <p className="text-sm text-garage-text-muted p-3">
              {categoryFilter
                ? t('addressBookAutocomplete.noMatchesInCategory', {
                    query: value,
                    category: categoryFilter,
                  })
                : t('addressBookAutocomplete.noMatches', { query: value })}
            </p>
          )}
          {combobox.expanded && (
            <div {...combobox.listProps}>
              {entries.map((entry, index) => (
                <div
                  key={entry.id}
                  {...combobox.optionProps(index)}
                  className={`w-full text-left px-3 py-2 cursor-pointer hover:bg-garage-bg transition-colors ${
                    index === combobox.activeIndex ? 'bg-garage-bg' : ''
                  }`}
                >
                  <div className="text-sm text-garage-text">{formatEntryDisplay(entry)}</div>
                  {entry.address && (
                    <div className="text-xs text-garage-text-muted mt-0.5">{entry.address}</div>
                  )}
                </div>
              ))}
              {showAddNew && (
                <div
                  {...combobox.optionProps(entries.length)}
                  className={`w-full text-left px-3 py-2 cursor-pointer border-t border-garage-border hover:bg-garage-bg transition-colors flex items-center gap-2 text-sm text-(--accent-fg) ${
                    combobox.activeIndex === entries.length ? 'bg-garage-bg' : ''
                  }`}
                >
                  <Plus className="w-4 h-4" aria-hidden="true" />
                  <span>{t('addressBookAutocomplete.addToAddressBook', { query: value })}</span>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      <div role="status" className="sr-only">
        {status}
      </div>

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
