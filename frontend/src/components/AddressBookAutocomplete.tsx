import { useState, useEffect, useRef } from 'react'
import type { AddressBookEntry } from '../types/addressBook'
import api from '../services/api'

interface AddressBookAutocompleteProps {
  value: string
  onChange: (value: string) => void
  onSelectEntry?: (entry: AddressBookEntry | null) => void
  categoryFilter?: string
  placeholder?: string
  className?: string
  id?: string
}

export default function AddressBookAutocomplete({
  value,
  onChange,
  onSelectEntry,
  categoryFilter,
  placeholder = 'Type to search...',
  className = '',
  id,
}: AddressBookAutocompleteProps) {
  const [entries, setEntries] = useState<AddressBookEntry[]>([])
  const [loading, setLoading] = useState(false)
  const [showDropdown, setShowDropdown] = useState(false)
  const [selectedIndex, setSelectedIndex] = useState(-1)
  const wrapperRef = useRef<HTMLDivElement>(null)

  // Search for entries when value changes
  useEffect(() => {
    const searchEntries = async () => {
      if (!value || value.length < 2) {
        setEntries([])
        setShowDropdown(false)
        return
      }

      try {
        setLoading(true)
        const params = new URLSearchParams()
        params.append('search', value)
        if (categoryFilter) params.append('category', categoryFilter)

        const response = await api.get(`/address-book?${params}`)
        setEntries(response.data.entries || [])
        setShowDropdown((response.data.entries || []).length > 0)
      } catch {
        setEntries([])
      } finally {
        setLoading(false)
      }
    }

    // Debounce the search
    const timeoutId = setTimeout(searchEntries, 300)
    return () => clearTimeout(timeoutId)
  }, [value, categoryFilter])

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(event.target as Node)) {
        setShowDropdown(false)
      }
    }

    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    onChange(e.target.value)
    setSelectedIndex(-1)
  }

  const handleSelectEntry = (entry: AddressBookEntry) => {
    onChange(entry.business_name || entry.name || '')
    setShowDropdown(false)
    if (onSelectEntry) {
      onSelectEntry(entry)
    }
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
        placeholder={placeholder}
        className={className}
        autoComplete="off"
      />

      {loading && (
        <div className="absolute right-3 top-1/2 -translate-y-1/2">
          <div className="w-4 h-4 border-2 border-primary border-t-transparent rounded-full animate-spin"></div>
        </div>
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
        <div className="absolute z-50 w-full mt-1 bg-garage-surface border border-garage-border rounded-md shadow-lg p-3">
          <p className="text-sm text-garage-text-muted">
            No contacts found matching "{value}"
            {categoryFilter && ` in ${categoryFilter} category`}
          </p>
        </div>
      )}

      <p className="text-xs text-garage-text-muted mt-1">
        Type at least 2 characters to search address book
      </p>
    </div>
  )
}
